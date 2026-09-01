import json
import zipfile
from pathlib import Path

from tg2notebooklm.model import Attachment, Chat, Message, PackageConfig
from tg2notebooklm.pack import build_package


def message(number: int) -> Message:
    return Message(
        id=str(number),
        sequence=number,
        kind="message",
        timestamp=f"2026-08-01T10:{number:02d}:00+00:00",
        author="Alice",
        text=" ".join(f"word{index}" for index in range(8)),
    )


def docx_attachment(number: int, path: Path) -> Attachment:
    return Attachment(
        reference=f"docs/{path.name}",
        path=path,
        name=path.name,
        kind="file",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        available=True,
        message_id=str(number),
    )


def make_docx(path: Path, paragraph: str) -> None:
    """Minimal valid DOCX: zip with content types, root rels, and one paragraph."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p></w:body>'
            "</w:document>",
        )


def docs_chat(tmp_path: Path):
    """Chat with three convertable DOCX attachments."""
    export_root = tmp_path / "export"
    documents = []
    chat_messages = []
    paragraphs = ["first document body", "second document body", "third document body"]
    for index, paragraph in enumerate(paragraphs, start=1):
        path = export_root / "docs" / f"note{index}.docx"
        make_docx(path, paragraph)
        msg = message(index)
        msg.attachments.append(docx_attachment(index, path))
        chat_messages.append(msg)
        documents.append(path)
    chat = Chat(name="Docs", kind="private_group", id="7", input_format="json", messages=chat_messages, export_root=export_root)
    return chat, documents


def test_packs_docx_into_single_docs_source(tmp_path: Path) -> None:
    chat, documents = docs_chat(tmp_path)
    output = tmp_path / "out"

    build_package([chat], output, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000, docs_to_markdown=True))

    sources = sorted((output / "sources").iterdir())
    docs_sources = [path for path in sources if path.name.startswith("docs_")]
    assert len(docs_sources) == 1
    content = docs_sources[0].read_text(encoding="utf-8")
    assert "# doc-01: note1.docx" in content
    assert "# doc-02: note2.docx" in content
    assert "# doc-03: note3.docx" in content
    assert "first document body" in content
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: (record["decision"], record.get("source")) for record in manifest["attachments"]}
    for name in ("note1.docx", "note2.docx", "note3.docx"):
        assert decisions[name] == ("docs_markdown", docs_sources[0].name)
    assert not list((output / "sources").glob("native_*"))
    summary = manifest["summary"]
    assert summary["docs_markdown_count"] == 1
    assert summary["native_source_count"] == 0


def test_docs_source_is_byte_deterministic(tmp_path: Path) -> None:
    chat, _documents = docs_chat(tmp_path)
    first_out = tmp_path / "out1"
    second_out = tmp_path / "out2"

    build_package([chat], first_out, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000, docs_to_markdown=True))
    build_package([chat], second_out, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000, docs_to_markdown=True))

    first = next((first_out / "sources").glob("docs_*.md")).read_bytes()
    second = next((second_out / "sources").glob("docs_*.md")).read_bytes()
    assert first == second


def test_docs_disabled_keeps_native_copies(tmp_path: Path) -> None:
    chat, documents = docs_chat(tmp_path)
    output = tmp_path / "out"

    build_package([chat], output, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000))

    sources = sorted((output / "sources").iterdir())
    assert not [path for path in sources if path.name.startswith("docs_")]
    natives = [path for path in sources if path.name.startswith("native_")]
    assert len(natives) == 3
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    for name in ("note1.docx", "note2.docx", "note3.docx"):
        assert decisions[name] == "native_source"


def test_single_doc_goes_native(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    path = export_root / "docs" / "solo.docx"
    make_docx(path, "lone document body")
    msg = message(1)
    msg.attachments.append(docx_attachment(1, path))
    chat = Chat(name="Docs", kind="private_group", id="7", input_format="json", messages=[msg], export_root=export_root)
    output = tmp_path / "out"

    build_package([chat], output, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000, docs_to_markdown=True))

    sources = sorted((output / "sources").iterdir())
    assert not [path for path in sources if path.name.startswith("docs_")]
    natives = [path for path in sources if path.name.startswith("native_")]
    assert len(natives) == 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attachments"][0]["decision"] == "native_source"
