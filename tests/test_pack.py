import json
from pathlib import Path

from PIL import Image

from tg2notebooklm.model import Attachment, Chat, Message, PackageConfig
from tg2notebooklm.pack import build_package


def message(number: int, words: int = 8) -> Message:
    return Message(
        id=str(number),
        sequence=number,
        kind="message",
        timestamp=f"2026-08-01T10:{number:02d}:00+00:00",
        author="Alice",
        text=" ".join(f"word{index}" for index in range(words)),
    )


def test_build_package_respects_word_and_source_limits(tmp_path: Path) -> None:
    chat = Chat(name="Research chat", kind="private_group", id="42", input_format="json", messages=[message(i) for i in range(1, 7)])
    output = tmp_path / "out"

    result = build_package([chat], output, PackageConfig(source_limit=3, target_words=150, hard_words=200))

    sources = sorted((output / "sources").iterdir())
    assert len(sources) <= 3
    assert sources[0].name == "00_index.md"
    markdown_sources = [path for path in sources if path.suffix == ".md" and path.name != "00_index.md"]
    assert markdown_sources
    assert all(len(path.read_text(encoding="utf-8").split()) <= 200 for path in markdown_sources)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["source_count"] == len(sources)
    assert result.source_count == len(sources)


def test_build_package_packs_images_into_pdf_and_records_context(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    image_path = export_root / "photos" / "one.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (32, 24), "red").save(image_path)
    msg = message(1)
    msg.attachments.append(
        Attachment(
            reference="photos/one.png",
            path=image_path,
            name="one.png",
            kind="photo",
            mime_type="image/png",
            available=True,
            message_id="1",
        )
    )
    chat = Chat(name="Images", kind="chat", id="1", input_format="json", messages=[msg], export_root=export_root)
    output = tmp_path / "out"

    build_package([chat], output, PackageConfig(source_limit=4, target_words=100, hard_words=120, images_per_page=4))

    pdfs = list((output / "sources").glob("*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].stat().st_size > 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attachments"][0]["decision"] == "image_atlas"
