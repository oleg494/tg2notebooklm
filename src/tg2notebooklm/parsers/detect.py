from __future__ import annotations

from pathlib import Path

from tg2notebooklm.model import Chat
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
    raise ValueError("Expected result.json or messages.html in the export directory")


def parse_export(path: Path) -> list[Chat]:
    format_name, resolved = detect_export(path)
    if format_name == "json":
        return parse_json_export(resolved)
    return [parse_html_export(resolved)]
