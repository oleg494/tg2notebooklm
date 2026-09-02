"""Upload-safety contract (D11): everything in sources/ uploads reliably.

Gemini Notebook transcribes audio on import and may reject speech-less or
low-quality audio/video ("Не удалось распознать речи"). Such media must never
sit in the guaranteed upload set. Sources split:

- ``sources/``        — upload-safe core: Markdown, PDF atlases, documents, CSV.
- ``optional_sources/`` — audio/video that usually transcribes, uploaded at
  the user's discretion; failures there never break the core promise.
"""
from __future__ import annotations

import json
from pathlib import Path

from tg2notebooklm.media import AUDIO_VIDEO_EXTENSIONS
from tg2notebooklm.model import Attachment, Chat, Message, PackageConfig
from tg2notebooklm.pack import build_package


def message(number: int, text: str = "hello") -> Message:
    return Message(
        id=str(number),
        sequence=number,
        kind="message",
        timestamp=f"2026-08-01T10:{number:02d}:00+00:00",
        author="Alice",
        text=text,
    )


def attachment(path: Path, number: int, name: str | None = None, kind: str = "file") -> Attachment:
    return Attachment(
        reference=f"files/{path.name}",
        path=path,
        name=name or path.name,
        kind=kind,
        mime_type="application/octet-stream",
        available=True,
        message_id=str(number),
    )


def chat_with(export_root: Path, messages: list[Message]) -> Chat:
    return Chat(name="Media chat", kind="private_group", id="1", input_format="json", messages=messages, export_root=export_root)


def test_sources_contains_no_audio_or_video(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    (files / "clip.mp4").write_bytes(b"fake mp4")
    (files / "voice.ogg").write_bytes(b"fake ogg")
    (files / "doc.pdf").write_bytes(b"fake pdf")

    msg = message(1)
    msg.attachments.append(attachment(files / "clip.mp4", 1, kind="video_file"))
    msg.attachments.append(attachment(files / "voice.ogg", 1, kind="voice_message"))
    msg.attachments.append(attachment(files / "doc.pdf", 1))
    output = tmp_path / "out"

    build_package([chat_with(export_root, [msg])], output, PackageConfig(source_limit=10, pack_native_pdfs=False))

    core = list((output / "sources").iterdir())
    for path in core:
        assert path.suffix.casefold() not in AUDIO_VIDEO_EXTENSIONS, f"{path.name} must not sit in sources/"
    optional = list((output / "optional_sources").iterdir())
    assert {p.suffix for p in optional} == {".mp4", ".ogg"}


def test_optional_sources_counter_and_manifest(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    (files / "voice.mp3").write_bytes(b"fake mp3")

    msg = message(1)
    msg.attachments.append(attachment(files / "voice.mp3", 1, kind="voice_message"))
    output = tmp_path / "out"

    result = build_package([chat_with(export_root, [msg])], output, PackageConfig(source_limit=10))

    # source_limit=3 reserves exactly index + catalog + one text chunk; media must go optional
    assert result.source_count == result.optional_source_count + result.core_source_count
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    optional_names = [record["name"] for record in manifest["sources"] if record["kind"] == "optional_media"]
    assert len(optional_names) == 1 and optional_names[0].endswith("__voice.mp3")
    assert (output / "optional_sources" / optional_names[0]).is_file()
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    assert decisions["voice.mp3"] == "optional_media"


def test_audio_video_never_consumes_core_slots(tmp_path: Path) -> None:
    """With a tight budget, media must not starve guaranteed core lanes."""
    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    (files / "clip.mp4").write_bytes(b"fake mp4")
    (files / "note.txt").write_bytes(b"b" * 4096)  # below 2MB inline threshold -> inlined into chat markdown

    msg1 = message(1)
    msg1.attachments.append(attachment(files / "clip.mp4", 1, kind="video_file"))
    msg2 = message(2, "plain text")
    output = tmp_path / "out"

    # source_limit=4: index + catalog + one text chunk + one optional media slot; core lanes untouched
    build_package([chat_with(export_root, [msg1, msg2])], output, PackageConfig(source_limit=4, target_words=100, hard_words=120))
    core = sorted(path.name for path in (output / "sources").iterdir())
    assert core == ["00_index.md", "01_attachments.csv", "chat_001-of-001__media-chat__msgs-1-2.md"]
    optional = list((output / "optional_sources").iterdir())
    assert len(optional) == 1


def test_no_native_files_flag_disables_optional_media_too(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    (files / "voice.mp3").write_bytes(b"fake mp3")

    msg = message(1)
    msg.attachments.append(attachment(files / "voice.mp3", 1, kind="voice_message"))
    output = tmp_path / "out"

    result = build_package([chat_with(export_root, [msg])], output, PackageConfig(source_limit=10, include_native_files=False))

    assert result.optional_source_count == 0
    assert not (output / "optional_sources").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    assert decisions["voice.mp3"] == "metadata_only"


def test_core_sources_are_within_configured_limit(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    files = export_root / "files"
    files.mkdir(parents=True)
    for index in range(6):
        (files / f"clip{index}.mp4").write_bytes(b"fake mp4")

    messages = []
    for index in range(6):
        msg = message(index + 1)
        msg.attachments.append(attachment(files / f"clip{index}.mp4", index + 1, kind="video_file"))
        messages.append(msg)
    output = tmp_path / "out"

    result = build_package([chat_with(export_root, messages)], output, PackageConfig(source_limit=5, target_words=100, hard_words=120))

    # Core budget exact; optional media capped by remaining budget semantics (plan minus core)
    core = list((output / "sources").iterdir())
    assert len(core) <= 5
    assert result.core_source_count == len(core)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["sources"]:
        if record["kind"] == "optional_media":
            assert (output / "optional_sources" / record["name"]).is_file()


def test_atlas_and_documents_stay_in_core() -> None:
    """Covered by test_pack.py / test_pdfpack.py: atlases and documents are core sources."""
