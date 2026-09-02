from __future__ import annotations

import hashlib
import re
import shutil

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from tg2notebooklm.model import Attachment, Chat, Message, PackageConfig
from tg2notebooklm.render import TEXT_ATTACHMENT_EXTENSIONS
from tg2notebooklm.security import safe_output_name

IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".ico", ".jp2", ".png", ".webp", ".tif", ".tiff",
    ".jpeg", ".jpg", ".jpe", ".heic", ".heif",
}
AUDIO_VIDEO_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aif", ".aifc", ".aiff", ".amr", ".au", ".avi",
    ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".ra", ".snd", ".wav", ".wma",
}
NATIVE_DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".csv", ".pptx", ".epub"}

# Pillow's bundled DejaVu-based font covers Latin + Cyrillic + CJK + emoji.
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = ImageFont.load_default(size=size)
    return _FONT_CACHE[size]


def _text_width(text: str, size: int) -> int:
    return _font(size).getbbox(text)[2]


def _wrap(text: str, size: int, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if _text_width(trial, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


@dataclass(slots=True)
class MediaCandidate:
    path: Path
    chat: Chat
    message: Message
    attachment: Attachment
    role: str = "primary"
    records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def suffix(self) -> str:
        return self.path.suffix.casefold()

    @property
    def display_name(self) -> str:
        if self.role == "thumbnail":
            return f"thumbnail for {self.attachment.name or self.attachment.kind}"
        return self.attachment.name or self.path.name


@dataclass(slots=True)
class AtlasResult:
    path: Path
    included: list[MediaCandidate]
    failed: list[tuple[MediaCandidate, str]]


def collect_candidates(chats: list[Chat]) -> tuple[list[MediaCandidate], list[dict[str, Any]]]:
    candidates_by_key: dict[tuple[Path, str], MediaCandidate] = {}
    records: list[dict[str, Any]] = []
    resolve_cache: dict[Path, Path] = {}

    def cached_resolve(path: Path) -> Path:
        resolved = resolve_cache.get(path)
        if resolved is None:
            resolved = path.resolve()
            resolve_cache[path] = resolved
        return resolved

    for chat in chats:
        root = chat.export_root
        for message in chat.messages:
            for attachment in message.attachments:
                relative_path = _relative_path(root, attachment.path, cached_resolve)
                record: dict[str, Any] = {
                    "chat": chat.name,
                    "chat_id": chat.id,
                    "message_id": message.id,
                    "timestamp": message.timestamp,
                    "author": message.author,
                    "name": attachment.name,
                    "kind": attachment.kind,
                    "mime_type": attachment.mime_type,
                    "reference": attachment.reference,
                    "path": relative_path,
                    "available": attachment.available,
                    "reason": attachment.reason,
                    "declared_size": attachment.size,
                    "dimensions": [attachment.width, attachment.height] if attachment.width and attachment.height else None,
                    "duration_seconds": attachment.duration_seconds,
                    "decision": "pending" if attachment.available and attachment.path else "unavailable",
                }
                records.append(record)
                if attachment.available and attachment.path:
                    _add_candidate(candidates_by_key, attachment.path, chat, message, attachment, "primary", record, resolver=cached_resolve)
                if attachment.thumbnail_path:
                    record["thumbnail_path"] = _relative_path(root, attachment.thumbnail_path, cached_resolve)
                    record["thumbnail_decision"] = "pending"
                    _add_candidate(candidates_by_key, attachment.thumbnail_path, chat, message, attachment, "thumbnail", record, resolver=cached_resolve)

    candidates = sorted(
        candidates_by_key.values(),
        key=lambda item: (item.message.sequence, item.chat.name.casefold(), str(item.path).casefold(), item.role),
    )
    return candidates, records


def classify_candidate(candidate: MediaCandidate, config: PackageConfig) -> str:
    suffix = candidate.suffix
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_VIDEO_EXTENSIONS:
        return "native"
    if suffix in NATIVE_DOCUMENT_EXTENSIONS:
        if suffix in TEXT_ATTACHMENT_EXTENSIONS and candidate.path.stat().st_size <= config.inline_text_max_bytes:
            return "inline_text"
        return "native"
    if suffix in TEXT_ATTACHMENT_EXTENSIONS and candidate.path.stat().st_size <= config.inline_text_max_bytes:
        return "inline_text"
    return "metadata_only"


def build_image_atlas(candidates: list[MediaCandidate], output_path: Path, config: PackageConfig) -> AtlasResult:
    """Render captioned photo-grid pages into a deterministic multi-page PDF.

    Pure Pillow pipeline (no reportlab): each page is rasterized at 150 DPI with
    captions drawn under every image, then encoded as a single-page PDF and
    concatenated with a minimal byte-level page merge. Works on CPython and Pyodide.
    """
    dpi = 150
    page_w = int(8.27 * dpi) if config.atlas_page_size.casefold() != "letter" else int(8.5 * dpi)
    page_h = int(11.69 * dpi) if config.atlas_page_size.casefold() != "letter" else int(11 * dpi)
    margin = int(0.35 * dpi)
    columns = 2 if config.images_per_page <= 8 else 3
    rows = max(1, -(-config.images_per_page // columns))
    cell_w = (page_w - margin * 2) // columns
    cell_h = (page_h - margin * 2) // rows

    included: list[MediaCandidate] = []
    failed: list[tuple[MediaCandidate, str]] = []
    page_images: list[Image.Image] = []
    page: Image.Image | None = None
    placed = 0

    for candidate in candidates:
        try:
            photo = _normalized_image(candidate.path)
        except Exception as exc:
            failed.append((candidate, str(exc)))
            continue
        if placed % config.images_per_page == 0:
            page = Image.new("RGB", (page_w, page_h), "white")
            page_images.append(page)
            placed = 0
        assert page is not None
        slot = placed
        col = slot % columns
        row = slot // columns
        x0 = margin + col * cell_w
        y0 = margin + row * cell_h
        _draw_cell(page, photo, candidate, x0, y0, cell_w, cell_h, dpi)
        included.append(candidate)
        placed += 1

    if not page_images:
        return AtlasResult(output_path, included, failed)
    _save_pdf_pages(page_images, output_path, dpi)
    return AtlasResult(output_path, included, failed)


def _draw_cell(page: Image.Image, photo: Image.Image, candidate: MediaCandidate, x0: int, y0: int, cell_w: int, cell_h: int, dpi: int) -> None:
    caption_size = max(11, dpi // 12)
    line_h = caption_size + 3
    caption_block_h = 4 * line_h + 8
    image_area_h = cell_h - caption_block_h

    scaled = ImageOps.contain(photo, (cell_w - 12, max(24, image_area_h - 8)))
    ix = x0 + (cell_w - scaled.width) // 2
    iy = y0 + 4 + (image_area_h - scaled.height) // 2
    page.paste(scaled, (ix, iy))

    draw = ImageDraw.Draw(page)
    message = candidate.message
    header = f"{candidate.chat.name} | msg {message.id} | {message.timestamp or 'unknown date'}"
    second = f"{message.author or 'unknown author'} | {candidate.display_name}"
    body = " ".join(message.text.split())[:220] if message.text.strip() else ""
    lines = _wrap(header, caption_size, cell_w - 10)[:1] + _wrap(second, caption_size, cell_w - 10)[:1] + _wrap(body, caption_size, cell_w - 10)[:2]
    text_y = y0 + image_area_h + 6
    for line in lines:
        draw.text((x0 + 5, text_y), line, fill=(40, 40, 40), font=_font(caption_size))
        text_y += line_h


def _save_pdf_pages(pages: list[Image.Image], output_path: Path, dpi: int) -> None:
    if len(pages) == 1:
        pages[0].save(output_path, "PDF", resolution=dpi)
    else:
        first, rest = pages[0], pages[1:]
        first.save(output_path, "PDF", resolution=dpi, save_all=True, append_images=rest)
    _pin_pdf_dates(output_path)


_FIXED_PDF_DATE = b"D:20000101000000Z"  # same length as Pillow's D:YYYYMMDDHHMMSSZ


def _pin_pdf_dates(path: Path) -> None:
    """Replace wall-clock Creation/ModDate with a constant for byte-determinism."""
    data = path.read_bytes()
    pinned = re.sub(
        rb"/(CreationDate|ModDate) \(D:\d{14}Z?\)",
        lambda m: b"/" + m.group(1) + b" (" + _FIXED_PDF_DATE + b")",
        data,
    )
    if pinned != data:
        path.write_bytes(pinned)



def copy_native_source(candidate: MediaCandidate, output_dir: Path, ordinal: int, digest: str | None = None) -> Path:
    digest = digest or file_digest(candidate.path)
    original_name = safe_output_name(candidate.path.name)
    target = output_dir / f"native_{ordinal:03d}__{digest}__{original_name}"
    shutil.copyfile(candidate.path, target)
    return target


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()[:8]


def mark_candidate(candidate: MediaCandidate, decision: str, *, source: str | None = None, reason: str | None = None) -> None:
    for record in candidate.records:
        key = "thumbnail_decision" if candidate.role == "thumbnail" else "decision"
        record[key] = decision
        if source:
            record["thumbnail_source" if candidate.role == "thumbnail" else "source"] = source
        if reason:
            record["thumbnail_reason" if candidate.role == "thumbnail" else "decision_reason"] = reason


def _add_candidate(
    candidates: dict[tuple[Path, str], MediaCandidate],
    path: Path,
    chat: Chat,
    message: Message,
    attachment: Attachment,
    role: str,
    record: dict[str, Any],
    *,
    resolver: Callable[[Path], Path],
) -> None:
    resolved = resolver(path)
    key = (resolved, role)
    if key not in candidates:
        candidates[key] = MediaCandidate(resolved, chat, message, attachment, role)
    candidates[key].records.append(record)


def _relative_path(root: Path | None, path: Path | None, resolver: Callable[[Path], Path] | None = None) -> str | None:
    if path is None:
        return None
    if root is not None:
        resolve = resolver or Path.resolve
        try:
            return resolve(path).relative_to(resolve(root)).as_posix()
        except ValueError:
            pass
    return path.name


def _normalized_image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image = image.convert("RGB")
        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        return image.copy()
