from __future__ import annotations

from pathlib import Path

from tg2notebooklm.model import Chat
from tg2notebooklm.parsers.file_dump import parse_file_dump
from tg2notebooklm.parsers.html_export import parse_html_export
from tg2notebooklm.parsers.json_export import parse_json_export


def detect_export(path: Path) -> tuple[str, Path]:
    candidate = Path(path)
    if candidate.is_file():
        if candidate.name.casefold() == "result.json" or candidate.suffix.casefold() == ".json":
            return "json", candidate
        if candidate.name.casefold().startswith("messages") and candidate.suffix.casefold() == ".html":
            return "html", candidate.parent
        raise ValueError(f"Unsupported Telegram export file: {candidate.name}")
    if not candidate.is_dir():
        raise FileNotFoundError(candidate)
    result = candidate / "result.json"
    if result.is_file():
        return "json", result
    if (candidate / "messages.html").is_file():
        return "html", candidate
    if any(p.is_file() for p in candidate.rglob("*")):
        return "file_dump", candidate
    raise ValueError("Expected result.json or messages.html in the export directory, or a non-empty folder of files")


def parse_export(path: Path) -> list[Chat]:
    format_name, resolved = detect_export(path)
    if format_name == "json":
        return parse_json_export(resolved)
    if format_name == "file_dump":
        return [parse_file_dump(resolved)]
    return [parse_html_export(resolved)]
