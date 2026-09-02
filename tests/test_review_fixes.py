import json
from pathlib import Path

import pytest

from tg2notebooklm.model import Chat, Message
from tg2notebooklm.pack import build_package
from tg2notebooklm.parsers.html_export import parse_html_export
from tg2notebooklm.security import UnsafePathError, resolve_export_path

PHOTO_WRAP_PAGE = """<!doctype html><html><body><div class="history">
  <div class="message default clearfix" id="message7">
    <div class="body">
      <div class="pull_right date details" title="01.08.2026 10:00:00 UTC+00:00">10:00</div>
      <div class="from_name">Alice</div>
      <div class="photo_wrap clearfix">
        <a class="photo clearfix" href="files/photo.png"><img class="photo" src="files/photo.png" style="width: 100%"/></a>
      </div>
      <div class="text">Photo caption</div>
    </div>
  </div>
</div></body></html>"""


def test_html_service_text_is_rendered_not_dropped(tmp_path: Path) -> None:
    page = """<!doctype html><html><body><div class="history">
      <div class="message service" id="message5"><div class="body details">Bob added Alice</div></div>
    </div></body></html>"""
    (tmp_path / "messages.html").write_text(page, encoding="utf-8")
    chat = parse_html_export(tmp_path)
    service = chat.messages[0]
    assert service.text == "Bob added Alice"
    from tg2notebooklm.render import render_message

    rendered = render_message(chat, service, 2_000_000)
    assert "Bob added Alice" in rendered


def test_downloaded_photo_wrap_yields_available_attachment(tmp_path: Path) -> None:
    from PIL import Image

    files = tmp_path / "files"
    files.mkdir()
    Image.new("RGB", (20, 20), "blue").save(files / "photo.png")
    (tmp_path / "messages.html").write_text(PHOTO_WRAP_PAGE, encoding="utf-8")

    chat = parse_html_export(tmp_path)
    message = chat.messages[0]
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.kind == "photo"
    assert attachment.available is True
    assert attachment.path is not None and attachment.path.name == "photo.png"


def test_empty_chat_package_does_not_crash(tmp_path: Path) -> None:
    chat = Chat(name="Empty", kind="personal_chat", id="1", input_format="json", messages=[])
    output = tmp_path / "out"
    result = build_package([chat], output, source_limit_config(tmp_path))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["message_count"] == 0
    assert result.source_count >= 2


def source_limit_config(tmp_path: Path):
    from tg2notebooklm.model import PackageConfig

    return PackageConfig(source_limit=4, target_words=100, hard_words=120)


def test_nul_byte_reference_is_rejected_as_unsafe(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "files/evil\x00.png")


def test_non_utf8_markdown_native_copy_does_not_crash(tmp_path: Path) -> None:
    from tg2notebooklm.model import Attachment, PackageConfig

    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    note = files / "note.md"
    note.write_bytes("Текст в cp1251: привет".encode("cp1251"))
    message = Message(id="1", sequence=0, kind="message", timestamp="2026-08-01T10:00:00", author="Alice", text="msg")
    message.attachments.append(
        Attachment(
            reference="files/note.md",
            path=note,
            name="note.md",
            kind="document",
            mime_type="text/markdown",
            available=True,
            message_id="1",
        )
    )
    chat = Chat(name="Cp1251", kind="personal_chat", id="1", input_format="json", messages=[message], export_root=export_root)
    output = tmp_path / "out"
    build_package([chat], output, PackageConfig(source_limit=4, target_words=100, hard_words=120, inline_text_max_bytes=8))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = [record["decision"] for record in manifest["attachments"]]
    assert "native_source" in decisions


def test_force_refuses_to_replace_export_root(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    (export_root / "files").mkdir(parents=True)
    (export_root / "result.json").write_text(
        json.dumps(
            {
                "name": "Guard chat",
                "type": "personal_chat",
                "id": 1,
                "messages": [
                    {
                        "id": 1,
                        "type": "message",
                        "date": "2026-08-01T10:00:00",
                        "date_unixtime": "1785578400",
                        "from": "Alice",
                        "from_id": "user1",
                        "text": "hello",
                        "text_entities": [{"type": "plain", "text": "hello"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    from tg2notebooklm.model import PackageConfig

    from tg2notebooklm.parsers.json_export import parse_json_export

    chats = parse_json_export(export_root / "result.json")
    with pytest.raises(ValueError, match="overlaps the export"):
        build_package(chats, export_root, PackageConfig(source_limit=4, force=True))
    assert (export_root / "result.json").exists()


def test_all_failed_atlas_group_is_marked_with_reason(tmp_path: Path) -> None:
    from tg2notebooklm.model import Attachment, PackageConfig

    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    broken = files / "broken.png"
    broken.write_bytes(b"not a real png")
    message = Message(id="1", sequence=0, kind="message", timestamp="2026-08-01T10:00:00", author="Alice", text="msg")
    message.attachments.append(
        Attachment(
            reference="files/broken.png",
            path=broken,
            name="broken.png",
            kind="photo",
            mime_type="image/png",
            available=True,
            message_id="1",
        )
    )
    chat = Chat(name="Broken", kind="personal_chat", id="1", input_format="json", messages=[message], export_root=export_root)
    output = tmp_path / "out"
    build_package([chat], output, PackageConfig(source_limit=4, target_words=100, hard_words=120))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    record = manifest["attachments"][0]
    assert record["decision"] == "metadata_only"
    assert record.get("decision_reason")
