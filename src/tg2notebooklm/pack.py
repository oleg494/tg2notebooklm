from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tg2notebooklm.enrich import enrich_chats
from tg2notebooklm.media import (
    AUDIO_VIDEO_EXTENSIONS,
    AtlasResult,
    MediaCandidate,
    build_image_atlas,
    classify_candidate,
    collect_candidates,
    copy_native_source,
    mark_candidate,
)
from tg2notebooklm.model import Chat, Message, PackageConfig, PackageResult
from tg2notebooklm.render import count_words, render_chat_header, render_message
from tg2notebooklm.security import safe_slug


@dataclass(slots=True)
class TextBlock:
    chat: Chat
    message: Message
    text: str


@dataclass(slots=True)
class TextChunk:
    parts: list[str] = field(default_factory=list)
    blocks: list[TextBlock] = field(default_factory=list)
    words: int = 0
    byte_count: int = 0

    @property
    def content(self) -> str:
        return "\n".join(self.parts).rstrip() + "\n"


@dataclass(slots=True)
class SourceRecord:
    name: str
    kind: str
    word_count: int | None
    byte_count: int
    sha256: str
    chats: list[str] = field(default_factory=list)
    first_message_id: str | None = None
    last_message_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "word_count": self.word_count,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "chats": self.chats,
            "first_message_id": self.first_message_id,
            "last_message_id": self.last_message_id,
        }


def build_package(chats: list[Chat], output_dir: Path, config: PackageConfig | None = None) -> PackageResult:
    config = config or PackageConfig()
    config.validate()
    if not chats:
        raise ValueError("No chats to package")

    output_dir = Path(output_dir).resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not config.force:
        raise FileExistsError(f"Output already exists: {output_dir}. Use --force to replace it.")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        sources_dir = staging / "sources"
        sources_dir.mkdir()
        warnings = enrich_chats(chats, config)
        candidates, attachment_records, _ = collect_candidates(chats)
        media_candidates = _deduplicate_candidates(candidates)

        blocks = _text_blocks(chats, config)
        text_chunks = _fit_text_chunks(blocks, chats, config)
        if len(text_chunks) > config.source_limit - 2:
            raise ValueError(
                "The text corpus cannot fit in the configured source limit without exceeding "
                f"{config.hard_words} words per source. Increase --source-limit or split the export."
            )

        source_records: list[SourceRecord] = []
        for ordinal, chunk in enumerate(text_chunks, start=1):
            name = _text_source_name(chunk, ordinal, len(text_chunks))
            path = sources_dir / name
            _write_text(path, chunk.content)
            source_records.append(_source_record(path, "chat_markdown", chunk))

        slots_remaining = config.source_limit - 2 - len(source_records)
        image_candidates = [candidate for candidate in media_candidates if classify_candidate(candidate, config) == "image"]
        native_candidates = [candidate for candidate in media_candidates if classify_candidate(candidate, config) == "native"]
        for candidate in media_candidates:
            classification = classify_candidate(candidate, config)
            if classification == "inline_text":
                mark_candidate(candidate, "inlined_in_chat_markdown")
            elif classification == "metadata_only":
                mark_candidate(candidate, "metadata_only", reason="File type is not a Gemini Notebook source and has no safe local extractor")

        atlas_count = 0
        if config.include_image_atlases and slots_remaining > 0 and image_candidates:
            groups = [image_candidates[index:index + config.images_per_atlas] for index in range(0, len(image_candidates), config.images_per_atlas)]
            for group in groups:
                if slots_remaining <= 0:
                    for candidate in group:
                        mark_candidate(candidate, "excluded_source_budget", reason="No source slots remained for another image atlas")
                    continue
                created = _create_bounded_atlases(group, sources_dir, atlas_count + 1, config, slots_remaining)
                for result in created:
                    if not result.included:
                        continue
                    atlas_count += 1
                    slots_remaining -= 1
                    for candidate in result.included:
                        mark_candidate(candidate, "image_atlas", source=result.path.name)
                    for candidate, reason in result.failed:
                        mark_candidate(candidate, "metadata_only", reason=f"Image atlas decoding failed: {reason}")
                    source_records.append(_source_record(result.path, "image_atlas"))
                if len(created) > slots_remaining + len(created):
                    break
        elif image_candidates:
            reason = "Image atlases disabled" if not config.include_image_atlases else "No source slots remained for image atlases"
            for candidate in image_candidates:
                mark_candidate(candidate, "metadata_only", reason=reason)

        native_count = 0
        selected_native_paths: set[Path] = set()
        for candidate in sorted(native_candidates, key=_native_priority):
            if candidate.path in selected_native_paths:
                mark_candidate(candidate, "native_source_duplicate", reason="Same file already selected through another message")
                continue
            if not config.include_native_files:
                mark_candidate(candidate, "metadata_only", reason="Native source copying disabled")
                continue
            if candidate.path.stat().st_size > config.max_source_bytes:
                mark_candidate(candidate, "metadata_only", reason=f"File exceeds configured source byte ceiling ({config.max_source_bytes})")
                continue
            if slots_remaining <= 0:
                mark_candidate(candidate, "excluded_source_budget", reason="No source slots remained")
                continue
            native_count += 1
            copied = copy_native_source(candidate, sources_dir, native_count)
            selected_native_paths.add(candidate.path)
            slots_remaining -= 1
            mark_candidate(candidate, "native_source", source=copied.name)
            source_records.append(_source_record(copied, "native_attachment"))

        catalog_path = sources_dir / "01_attachments.csv"
        _write_attachment_catalog(catalog_path, attachment_records)
        source_records.append(_source_record(catalog_path, "attachment_catalog"))

        index_path = sources_dir / "00_index.md"
        index_content = _render_index(chats, source_records, config, attachment_records, warnings)
        _write_text(index_path, index_content)
        source_records.insert(0, _source_record(index_path, "index"))

        if len(source_records) > config.source_limit:
            raise AssertionError("Internal error: source budget exceeded")
        _validate_sources(sources_dir, source_records, config)

        manifest = {
            "schema_version": 1,
            "generator": "tg2notebooklm 0.1.0",
            "config": _config_dict(config),
            "summary": {
                "chat_count": len(chats),
                "message_count": sum(len(chat.messages) for chat in chats),
                "attachment_count": len(attachment_records),
                "source_count": len(source_records),
                "text_source_count": len(text_chunks),
                "image_atlas_count": atlas_count,
                "attachment_catalog_count": 1,
                "native_source_count": native_count,
                "unavailable_attachments": sum(not record["available"] for record in attachment_records),
                "excluded_by_budget": sum(record.get("decision") == "excluded_source_budget" for record in attachment_records),
            },
            "chats": [
                {
                    "name": chat.name,
                    "id": chat.id,
                    "type": chat.kind,
                    "input_format": chat.input_format,
                    "message_count": len(chat.messages),
                }
                for chat in chats
            ],
            "sources": [record.as_dict() for record in source_records],
            "attachments": attachment_records,
            "warnings": warnings,
        }
        _write_text(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        _write_text(staging / "report.md", _render_report(manifest))

        if output_dir.exists():
            if output_dir.is_dir():
                shutil.rmtree(output_dir)
            else:
                output_dir.unlink()
        staging.replace(output_dir)
        return PackageResult(
            output_dir=output_dir,
            source_count=len(source_records),
            attachment_catalog_count=1,
            text_source_count=len(text_chunks),
            image_atlas_count=atlas_count,
            native_source_count=native_count,
            message_count=sum(len(chat.messages) for chat in chats),
            attachment_count=len(attachment_records),
            warnings=warnings,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _text_blocks(chats: list[Chat], config: PackageConfig) -> list[TextBlock]:
    return [
        TextBlock(chat, message, render_message(chat, message, config.inline_text_max_bytes))
        for chat in chats
        for message in chat.messages
    ]


def _fit_text_chunks(blocks: list[TextBlock], chats: list[Chat], config: PackageConfig) -> list[TextChunk]:
    max_slots = config.source_limit - 2
    chunks = _pack_text(blocks, chats, config.target_words, config)
    if len(chunks) <= max_slots:
        return chunks
    low = config.target_words + 1
    high = config.hard_words
    best = _pack_text(blocks, chats, high, config)
    if len(best) > max_slots:
        return best
    while low <= high:
        middle = (low + high) // 2
        attempt = _pack_text(blocks, chats, middle, config)
        if len(attempt) <= max_slots:
            best = attempt
            high = middle - 1
        else:
            low = middle + 1
    return best


def _pack_text(blocks: list[TextBlock], chats: list[Chat], target_words: int, config: PackageConfig) -> list[TextChunk]:
    if not blocks:
        header = "# Empty Telegram export\n\nNo messages were present in the selected export.\n"
        return [TextChunk([header], [], count_words(header), len(header.encode("utf-8")))]

    chunks: list[TextChunk] = []
    current = TextChunk()
    active_chat: Chat | None = None
    corpus_header = _corpus_header(chats)

    def start_chunk(chat: Chat) -> None:
        nonlocal current, active_chat
        current = TextChunk()
        _append_part(current, corpus_header)
        _append_part(current, render_chat_header(chat))
        active_chat = chat

    def flush() -> None:
        nonlocal current, active_chat
        if current.blocks:
            chunks.append(current)
        current = TextChunk()
        active_chat = None

    for block in blocks:
        if not current.parts:
            start_chunk(block.chat)
        elif active_chat is not block.chat:
            chat_header = render_chat_header(block.chat)
            if _would_exceed(current, chat_header + "\n" + block.text, target_words, config.max_source_bytes):
                flush()
                start_chunk(block.chat)
            else:
                _append_part(current, chat_header)
                active_chat = block.chat

        if current.blocks and _would_exceed(current, block.text, target_words, config.max_source_bytes):
            flush()
            start_chunk(block.chat)
        continuation_reserve = count_words(f"### Continuation · msg {block.message.id} · part 999/999")
        max_block_words = max(1, config.hard_words - current.words - continuation_reserve)
        max_block_bytes = max(1, config.max_source_bytes - current.byte_count - 512)
        pieces = _split_oversized(block.text, max_block_words, max_block_bytes)
        for piece_index, piece in enumerate(pieces, start=1):
            if piece_index > 1:
                flush()
                start_chunk(block.chat)
                marker = f"### Continuation · msg {block.message.id} · part {piece_index}/{len(pieces)}\n"
                _append_part(current, marker)
            _append_part(current, piece)
            current.blocks.append(block)
            if current.words > config.hard_words or current.byte_count > config.max_source_bytes:
                raise ValueError(f"Message {block.message.id} cannot fit within one Gemini Notebook source")
    flush()
    return chunks


def _split_oversized(text: str, max_words: int, max_bytes: int) -> list[str]:
    if count_words(text) <= max_words and len(text.encode("utf-8")) <= max_bytes:
        return [text]
    tokens = text.split()
    if not tokens:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for token in tokens:
        token_bytes = len(token.encode("utf-8")) + (1 if current else 0)
        if current and (len(current) + 1 > max_words or current_bytes + token_bytes > max_bytes):
            pieces.append(" ".join(current))
            current = []
            current_bytes = 0
        current.append(token)
        current_bytes += len(token.encode("utf-8")) + (1 if len(current) > 1 else 0)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _append_part(chunk: TextChunk, text: str) -> None:
    chunk.parts.append(text.rstrip())
    chunk.words += count_words(text)
    chunk.byte_count += len(text.rstrip().encode("utf-8")) + 1


def _would_exceed(chunk: TextChunk, text: str, target_words: int, max_bytes: int) -> bool:
    return chunk.words + count_words(text) > target_words or chunk.byte_count + len(text.encode("utf-8")) + 1 > max_bytes


def _corpus_header(chats: list[Chat]) -> str:
    return (
        "# Telegram export corpus\n\n"
        "This source was generated locally by tg2notebooklm. Message IDs, reply targets, dates, authors, "
        "forwards, reactions, polls, service events, media metadata, and unavailable-file reasons are retained.\n"
        f"Chats represented in this source set: {len(chats)}.\n"
    )


def _text_source_name(chunk: TextChunk, ordinal: int, total: int) -> str:
    unique_chats = list(dict.fromkeys(block.chat.name for block in chunk.blocks))
    scope = safe_slug(unique_chats[0]) if len(unique_chats) == 1 else "telegram-corpus"
    first = safe_slug(chunk.blocks[0].message.id, "first", 24)
    last = safe_slug(chunk.blocks[-1].message.id, "last", 24)
    return f"chat_{ordinal:03d}-of-{total:03d}__{scope}__msgs-{first}-{last}.md"


def _deduplicate_candidates(candidates: list[MediaCandidate]) -> list[MediaCandidate]:
    by_path: dict[Path, MediaCandidate] = {}
    for candidate in candidates:
        existing = by_path.get(candidate.path)
        if existing is None:
            by_path[candidate.path] = candidate
            continue
        existing.records.extend(record for record in candidate.records if record not in existing.records)
        existing.contexts.extend(context for context in candidate.contexts if context not in existing.contexts)
        if existing.role == "thumbnail" and candidate.role == "primary":
            candidate.records = existing.records
            candidate.contexts = existing.contexts
            by_path[candidate.path] = candidate
    return list(by_path.values())


def _create_bounded_atlases(
    group: list[MediaCandidate],
    sources_dir: Path,
    first_ordinal: int,
    config: PackageConfig,
    slots_available: int,
) -> list[AtlasResult]:
    results: list[AtlasResult] = []

    def create(items: list[MediaCandidate]) -> None:
        if not items or len(results) >= slots_available:
            for candidate in items:
                mark_candidate(candidate, "excluded_source_budget", reason="No source slots remained while splitting image atlas")
            return
        ordinal = first_ordinal + len(results)
        path = sources_dir / f"images_{ordinal:03d}.pdf"
        result = build_image_atlas(items, path, config)
        if path.exists() and path.stat().st_size > config.max_source_bytes and len(items) > 1:
            path.unlink(missing_ok=True)
            middle = len(items) // 2
            create(items[:middle])
            create(items[middle:])
            return
        if path.exists() and path.stat().st_size > config.max_source_bytes:
            path.unlink(missing_ok=True)
            for candidate in items:
                mark_candidate(candidate, "metadata_only", reason="Image cannot fit below configured source byte ceiling")
            return
        results.append(result)

    create(group)
    return results


def _native_priority(candidate: MediaCandidate) -> tuple[int, int, int, int, str]:
    suffix = candidate.suffix
    if suffix in {".pdf", ".docx", ".pptx", ".epub"}:
        category = 0
    elif suffix in {".txt", ".md", ".csv"}:
        category = 1
    elif suffix in AUDIO_VIDEO_EXTENSIONS:
        category = 2
    else:
        category = 3
    kind_boost = 1 if candidate.attachment.kind in {"voice_message", "video_message", "audio_file"} else 0
    return (category, kind_boost, -candidate.path.stat().st_size, candidate.message.sequence, str(candidate.path).casefold())


def _render_index(
    chats: list[Chat],
    sources: list[SourceRecord],
    config: PackageConfig,
    attachments: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    lines = [
        "# Telegram → Gemini Notebook source index",
        "",
        "Upload **every file in this `sources` directory** to one Gemini Notebook notebook. "
        "Keep `manifest.json` and `report.md` locally for audit; they are not source slots.",
        "",
        "## Package limits",
        "",
        f"- Configured source limit: {config.source_limit}",
        f"- Chat Markdown target: {config.target_words:,} words",
        f"- Chat Markdown hard ceiling: {config.hard_words:,} words",
        f"- Uploaded-source byte ceiling used by the converter: {config.max_source_bytes:,}",
        "",
        "## Chats",
        "",
    ]
    for chat in chats:
        ids = [message.id for message in chat.messages]
        lines.append(f"- **{chat.name}** — {len(chat.messages):,} records; IDs {ids[0] if ids else 'none'}…{ids[-1] if ids else 'none'}; input `{chat.input_format}`")
    lines.extend(["", "## Sources", ""])
    for source in sources:
        details = [source.kind, f"{source.byte_count:,} bytes"]
        if source.word_count is not None:
            details.append(f"{source.word_count:,} words")
        if source.first_message_id:
            details.append(f"messages {source.first_message_id}…{source.last_message_id}")
        lines.append(f"- `{source.name}` — " + "; ".join(details))
    unavailable = sum(not item["available"] for item in attachments)
    excluded = sum(item.get("decision") == "excluded_source_budget" for item in attachments)
    lines.extend([
        "",
        "## Attachment audit",
        "",
        f"- Attachment records: {len(attachments):,}",
        f"- Not present in Telegram export: {unavailable:,}",
        f"- Excluded only because the source budget was full: {excluded:,}",
        "- Exact per-message decisions and missing-file reasons are in local `manifest.json`. "
        "It is intentionally outside `sources/`; upload it separately only if you want the audit data analyzed.",
    ])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend([
        "",
        "## Query hints",
        "",
        "Ask with a chat name, date range, Telegram message ID, author, topic, attachment name, or source filename. "
        "For example: `Compare messages 1200–1500 with the images cited in images_001.pdf.`",
        "",
    ])
    return "\n".join(lines)


def _render_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    decisions: dict[str, int] = {}
    for record in manifest["attachments"]:
        decision = record.get("decision", "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
    lines = [
        "# tg2notebooklm conversion report",
        "",
        f"- Chats: {summary['chat_count']}",
        f"- Messages/service records: {summary['message_count']:,}",
        f"- Attachment records: {summary['attachment_count']:,}",
        f"- Files to upload: {summary['source_count']}",
        f"- Chat Markdown sources: {summary['text_source_count']}",
        f"- Image atlas PDFs: {summary['image_atlas_count']}",
        f"- Native attachment sources: {summary['native_source_count']}",
        "",
        "## Attachment decisions",
        "",
    ]
    lines.extend(f"- `{decision}`: {count:,}" for decision, count in sorted(decisions.items()))
    if manifest["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in manifest["warnings"])
    lines.extend([
        "",
        "## Audit-file usage",
        "",
        "`manifest.json` and this report stay outside `sources/` so the configured source budget is exact. "
        "Upload `manifest.json` separately only when per-message inclusion/exclusion analysis is required.",
        "",
        "## Privacy",
        "",
        "The converter made no network requests. Generated sources contain the chat content and participant names from the export; review them before uploading or publishing.",
        "",
    ])
    return "\n".join(lines)


def _write_attachment_catalog(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "chat", "chat_id", "message_id", "timestamp", "author", "name", "kind", "mime_type",
        "reference", "path", "available", "reason", "declared_size", "dimensions",
        "duration_seconds", "decision", "source", "decision_reason", "thumbnail_path",
        "thumbnail_decision", "thumbnail_source", "thumbnail_reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in fields}
            if isinstance(row.get("dimensions"), list):
                row["dimensions"] = "x".join(str(value) for value in row["dimensions"])
            writer.writerow(row)


def _source_record(path: Path, kind: str, chunk: TextChunk | None = None) -> SourceRecord:
    data = path.read_bytes()
    return SourceRecord(
        name=path.name,
        kind=kind,
        word_count=count_words(data.decode("utf-8")) if path.suffix.casefold() == ".md" else None,
        byte_count=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        chats=list(dict.fromkeys(block.chat.name for block in chunk.blocks)) if chunk else [],
        first_message_id=chunk.blocks[0].message.id if chunk and chunk.blocks else None,
        last_message_id=chunk.blocks[-1].message.id if chunk and chunk.blocks else None,
    )


def _validate_sources(sources_dir: Path, sources: list[SourceRecord], config: PackageConfig) -> None:
    actual = sorted(path.name for path in sources_dir.iterdir() if path.is_file())
    expected = sorted(source.name for source in sources)
    if actual != expected:
        raise AssertionError("Manifest source list does not match sources directory")
    for source in sources:
        if source.byte_count > config.max_source_bytes:
            raise ValueError(f"Generated source exceeds byte ceiling: {source.name}")
        if source.word_count is not None and source.kind == "chat_markdown" and source.word_count > config.hard_words:
            raise ValueError(f"Generated source exceeds word ceiling: {source.name}")


def _config_dict(config: PackageConfig) -> dict[str, Any]:
    return {
        "source_limit": config.source_limit,
        "target_words": config.target_words,
        "hard_words": config.hard_words,
        "max_source_bytes": config.max_source_bytes,
        "images_per_page": config.images_per_page,
        "images_per_atlas": config.images_per_atlas,
        "inline_text_max_bytes": config.inline_text_max_bytes,
        "include_native_files": config.include_native_files,
        "include_image_atlases": config.include_image_atlases,
        "transcribe_audio": config.transcribe_audio,
        "whisper_model": config.whisper_model,
        "whisper_language": config.whisper_language,
        "ocr_images": config.ocr_images,
        "ocr_languages": config.ocr_languages,
        "enrichment_max_files": config.enrichment_max_files,
    }


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
