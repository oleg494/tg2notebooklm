from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tg2notebooklm.media import classify_candidate, collect_candidates
from tg2notebooklm.model import PackageConfig
from tg2notebooklm.docspack import markitdown_available
from tg2notebooklm.parsers import detect_export, parse_export
from tg2notebooklm.pack import build_package
from tg2notebooklm.render import count_words

PLAN_LIMITS = {
    "standard": 50,
    "plus": 100,
    "pro": 300,
    "ultra20": 500,
    "ultra30": 600,
}


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            payload = inspect_export(args.input, args.plan, args.source_limit)
        else:
            config = _config_from_args(args)
            if config.docs_to_markdown and not markitdown_available():
                print(
                    "error: --docs-to-markdown requires the optional docs extra; install it with: pip install tg2notebooklm[docs]",
                    file=sys.stderr,
                )
                return 2
            chats = parse_export(args.input)
            result = build_package(chats, args.output, config)
            payload = result.as_dict()
            for warning in result.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            print(
                f"Done: {result.source_count} sources in {args.output}. "
                "Upload the files from sources/ to your notebook; keep manifest.json and report.md for reference.",
                file=sys.stderr,
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except FileNotFoundError as exc:
        hint = ""
        if getattr(args, "input", None) is not None:
            hint = f" Check the path or run: tg2notebooklm inspect {args.input}"
        print(f"error: {exc}.{hint}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"error: {args.input} is not valid JSON ({exc}). "
            "The export may be truncated — re-export from Telegram Desktop (Settings > Advanced > Export Telegram data).",
            file=sys.stderr,
        )
        return 2
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


def inspect_export(input_path: Path, plan: str = "standard", source_limit: int | None = None) -> dict[str, object]:
    format_name, resolved = detect_export(input_path)
    chats = parse_export(resolved)
    limit = source_limit or PLAN_LIMITS[plan]
    config = PackageConfig(source_limit=limit)
    candidates, attachments = collect_candidates(chats)
    classification: dict[str, int] = {}
    for candidate in candidates:
        kind = classify_candidate(candidate, config)
        classification[kind] = classification.get(kind, 0) + 1
    text_words = sum(count_words(message.text) for chat in chats for message in chat.messages)
    estimated_markdown_sources = max(1, (text_words + config.target_words - 1) // config.target_words)
    return {
        "format": format_name,
        "input": str(resolved),
        "chats": len(chats),
        "messages": sum(len(chat.messages) for chat in chats),
        "service_records": sum(message.kind != "message" for chat in chats for message in chat.messages),
        "text_words": text_words,
        "attachments": len(attachments),
        "available_attachments": sum(record["available"] for record in attachments),
        "unavailable_attachments": sum(not record["available"] for record in attachments),
        "unique_local_media_candidates": len(candidates),
        "candidate_classes": classification,
        "configured_source_limit": limit,
        "estimated_chat_markdown_sources": estimated_markdown_sources,
        "estimated_slots_after_index_and_chat": max(0, limit - 2 - estimated_markdown_sources),
        "note": "Estimate excludes Markdown metadata overhead and PDF atlas splitting; convert enforces exact limits.",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg2notebooklm",
        description="Convert Telegram Desktop exports into source-budgeted Gemini Notebook / NotebookLM files.",
    )
    parser.add_argument("--version", action="version", version="tg2notebooklm 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect an export without writing chat content")
    inspect_parser.add_argument("input", type=Path, help="Telegram export directory, result.json, or messages.html")
    _add_budget_arguments(inspect_parser)

    convert_parser = subparsers.add_parser("convert", help="Build a Gemini Notebook source package")
    convert_parser.add_argument("input", type=Path, help="Telegram export directory, result.json, or messages.html")
    convert_parser.add_argument("--output", "-o", type=Path, default=Path("tg2notebooklm-out"), help="Output directory (default: ./tg2notebooklm-out)")
    _add_budget_arguments(convert_parser)
    convert_parser.add_argument("--target-words", type=int, default=400_000, help="Preferred words per chat Markdown source")
    convert_parser.add_argument("--hard-words", type=int, default=500_000, help="Hard words per chat Markdown source (max 500000)")
    convert_parser.add_argument("--max-source-mb", type=int, default=190, help="Conservative uploaded-source byte ceiling")
    convert_parser.add_argument("--inline-text-mb", type=int, default=2, help="Inline small text attachments up to this size")
    convert_parser.add_argument("--images-per-page", type=int, default=8, help="Images on each PDF atlas page")
    convert_parser.add_argument("--images-per-atlas", type=int, default=160, help="Preferred images per PDF atlas source")
    convert_parser.add_argument("--no-image-atlases", action="store_true", help="Keep images as metadata only")
    convert_parser.add_argument("--no-native-files", action="store_true", help="Do not copy audio/video/document files as sources")
    convert_parser.add_argument("--no-pdf-packing", action="store_true", help="Keep small PDFs as separate native sources instead of merging them")
    convert_parser.add_argument("--pdf-pack-max-mb", type=int, default=20, help="Max single-PDF size for merged packing (MB)")
    convert_parser.add_argument("--docs-to-markdown", action="store_true", help="Convert small DOCX/PPTX/EPUB to Markdown and pack into shared docs_*.md sources (requires docs extra)")
    convert_parser.add_argument("--docs-pack-max-mb", type=int, default=20, help="Max single-document size for Markdown conversion packing (MB)")
    convert_parser.add_argument("--transcribe-audio", action="store_true", help="Locally transcribe exported audio before packing (requires transcribe extra)")
    convert_parser.add_argument("--whisper-model", default="small", help="faster-whisper model name or local path")
    convert_parser.add_argument("--whisper-language", default=None, help="Optional language code; default auto-detect")
    convert_parser.add_argument("--ocr-images", action="store_true", help="Locally OCR images before packing (requires Tesseract executable)")
    convert_parser.add_argument("--ocr-languages", default="eng+rus", help="Tesseract language expression")
    convert_parser.add_argument("--enrichment-max-files", type=int, default=0, help="Cap OCR/transcription files; 0 means unlimited")
    convert_parser.add_argument("--force", action="store_true", help="Replace an existing output directory after successful conversion")
    return parser


def _add_budget_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", choices=PLAN_LIMITS, default="standard", help="Gemini Notebook plan budget: standard=50 sources, plus=100, pro=300, ultra20=500, ultra30=600")
    parser.add_argument("--source-limit", type=int, default=None, help="Override plan source count")


def _config_from_args(args: argparse.Namespace) -> PackageConfig:
    source_limit = args.source_limit or PLAN_LIMITS[args.plan]
    return PackageConfig(
        source_limit=source_limit,
        target_words=args.target_words,
        hard_words=args.hard_words,
        max_source_bytes=args.max_source_mb * 1024 * 1024,
        images_per_page=args.images_per_page,
        images_per_atlas=args.images_per_atlas,
        inline_text_max_bytes=args.inline_text_mb * 1024 * 1024,
        include_native_files=not args.no_native_files,
        include_image_atlases=not args.no_image_atlases,
        pack_native_pdfs=not args.no_pdf_packing,
        pdf_pack_max_mb=args.pdf_pack_max_mb,
        docs_to_markdown=args.docs_to_markdown,
        docs_pack_max_mb=args.docs_pack_max_mb,
        transcribe_audio=args.transcribe_audio,
        whisper_model=args.whisper_model,
        whisper_language=args.whisper_language,
        ocr_images=args.ocr_images,
        ocr_languages=args.ocr_languages,
        enrichment_max_files=args.enrichment_max_files,
        force=args.force,
    )


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
