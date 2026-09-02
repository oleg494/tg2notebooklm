"""File-dump mode (D10): any folder of files becomes a source-budgeted package."""
from __future__ import annotations

import json
from pathlib import Path

from tg2notebooklm.model import PackageConfig
from tg2notebooklm.pack import build_package
from tg2notebooklm.parsers import detect_export, parse_export
from tg2notebooklm.parsers.file_dump import parse_file_dump


def make_dump(tmp_path: Path) -> Path:
    dump = tmp_path / "dump"
    (dump / "notes").mkdir(parents=True)
    (dump / "readme.md").write_text("# hello world\n", encoding="utf-8")
    (dump / "notes" / "a.txt").write_text("plain text note\n", encoding="utf-8")
    (dump / "notes" / "b.py").write_text("print(1)\n", encoding="utf-8")
    return dump


def test_detects_file_dump_folder(tmp_path: Path) -> None:
    format_name, resolved = detect_export(make_dump(tmp_path))
    assert format_name == "file_dump"
    assert resolved.name == "dump"


def test_parse_file_dump_orders_files_deterministically(tmp_path: Path) -> None:
    chat = parse_file_dump(make_dump(tmp_path))
    assert chat.input_format == "file_dump"
    assert chat.kind == "folder_dump"
    references = [attachment.reference for message in chat.messages for attachment in message.attachments]
    assert references == ["notes/a.txt", "notes/b.py", "readme.md"]
    assert all(message.attachments[0].available for message in chat.messages)
    assert all(message.attachments[0].size is not None for message in chat.messages)


def test_build_package_from_dump_inlines_text_and_renders_neutral_headers(tmp_path: Path) -> None:
    chats = parse_export(make_dump(tmp_path))
    out = tmp_path / "out"
    result = build_package(chats, out, PackageConfig(source_limit=8))

    chunk = next((out / "sources").glob("chat_*.md"))
    content = chunk.read_text(encoding="utf-8")
    assert "# File dump corpus" in content
    assert "# File dump: dump" in content
    assert "### File 1 · dump · file-000001" in content
    assert "plain text note" in content  # small text file inlined
    assert "Telegram" not in content

    index = (out / "sources" / "00_index.md").read_text(encoding="utf-8")
    assert "File dump → Gemini Notebook source index" in index
    assert "## Dumps" in index
    assert "Telegram" not in index.split("## Query hints")[0].split("## Attachment audit")[0]

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    assert decisions == {
        "a.txt": "inlined_in_chat_markdown",
        "b.py": "inlined_in_chat_markdown",
        "readme.md": "inlined_in_chat_markdown",
    }


def test_dump_is_byte_deterministic(tmp_path: Path) -> None:
    dump = make_dump(tmp_path)
    first_out = tmp_path / "out1"
    second_out = tmp_path / "out2"
    config = PackageConfig(source_limit=8)

    build_package([parse_file_dump(dump)], first_out, config)
    build_package([parse_file_dump(dump)], second_out, config)

    first = sorted(p.name for p in (first_out / "sources").iterdir())
    second = sorted(p.name for p in (second_out / "sources").iterdir())
    assert first == second
    for name in first:
        assert (first_out / "sources" / name).read_bytes() == (second_out / "sources" / name).read_bytes()


def test_dump_rejects_empty_folder(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    try:
        detect_export(empty)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Expected result.json or messages.html" in str(exc)


def test_dump_rejects_oversized_folder(tmp_path: Path) -> None:
    big = tmp_path / "big"
    big.mkdir()
    for index in range(10):
        (big / f"f{index:03d}.txt").write_text("x", encoding="utf-8")
    from tg2notebooklm.parsers.file_dump import MAX_FILES

    original = MAX_FILES
    import tg2notebooklm.parsers.file_dump as module

    module.MAX_FILES = 5
    try:
        parse_file_dump(big)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "split it into smaller dumps" in str(exc)
    finally:
        module.MAX_FILES = original
