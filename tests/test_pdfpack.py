import hashlib
import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

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


def pdf_attachment(number: int, path: Path) -> Attachment:
    return Attachment(
        reference=f"docs/{path.name}",
        path=path,
        name=path.name,
        kind="file",
        mime_type="application/pdf",
        available=True,
        message_id=str(number),
    )


def make_pdf(path: Path, color: tuple[int, int, int]) -> None:
    """Solid-color single-page PDF; image-only, so it is scan-gated (no text layer)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), color).save(path, "PDF", resolution=150)


def make_text_pdf(path: Path, label: str) -> None:
    """Single-page PDF with a real text layer (born-digital)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"0 0 1 rg 0 0 400 300 re f 0 0 0 rg BT /F1 18 Tf 36 260 Td ({label}) Tj ET".encode()
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    raw = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(raw))
        raw += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(raw)
    raw += f"xref\n0 {len(bodies) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        raw += f"{offset:010d} 00000 n \n".encode()
    raw += f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    path.write_bytes(bytes(raw))


def packed_chat(tmp_path: Path):
    """Chat with three born-digital PDFs and one scanned-like PDF."""
    export_root = tmp_path / "export"
    documents = []
    paths = [
        ("one.pdf", (255, 0, 0), "alpha"),
        ("two.pdf", (0, 255, 0), "beta"),
        ("three.pdf", (0, 0, 255), "gamma"),
    ]
    chat_messages = []
    for index, (name, color, label) in enumerate(paths, start=1):
        path = export_root / "docs" / name
        make_text_pdf(path, label)
        msg = message(index)
        msg.attachments.append(pdf_attachment(index, path))
        chat_messages.append(msg)
        documents.append(path)
    scan_path = export_root / "docs" / "scan.pdf"
    make_pdf(scan_path, (128, 128, 128))
    scan_msg = message(4)
    scan_msg.attachments.append(pdf_attachment(4, scan_path))
    chat_messages.append(scan_msg)
    chat = Chat(name="Docs", kind="private_group", id="7", input_format="json", messages=chat_messages, export_root=export_root)
    return chat, documents, scan_path


def test_packs_born_digital_pdfs_and_scan_gates(tmp_path: Path) -> None:
    chat, documents, scan_path = packed_chat(tmp_path)
    output = tmp_path / "out"

    build_package([chat], output, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000))

    sources = output / "sources"
    merged = list(sources.glob("native_docs_*.pdf"))
    assert len(merged) == 1
    reader = PdfReader(merged[0])
    assert len(reader.pages) == 6  # 3 cover pages + 3 document pages
    for cover_index in (0, 2, 4):
        cover = reader.pages[cover_index].mediabox
        doc = reader.pages[cover_index + 1].mediabox
        assert abs(float(cover.width) - float(doc.width)) < 1
        assert abs(float(cover.height) - float(doc.height)) < 1
    natives = [path for path in sources.iterdir() if path.name.startswith("native_") and not path.name.startswith("native_docs_")]
    assert len(natives) == 1
    assert natives[0].name.endswith("__scan.pdf")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    assert decisions["one.pdf"] == "native_source"
    assert decisions["two.pdf"] == "native_source"
    assert decisions["three.pdf"] == "native_source"
    assert decisions["scan.pdf"] == "native_source"
    packed_names = {record["name"]: record.get("source") for record in manifest["attachments"] if record.get("source", "").startswith("native_docs_")}
    assert set(packed_names.values()) == {merged[0].name}


def test_merged_pdf_is_byte_deterministic(tmp_path: Path) -> None:
    chat, _documents, _scan = packed_chat(tmp_path)
    first = tmp_path / "out1"
    second = tmp_path / "out2"

    build_package([chat], first, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000))
    build_package([chat], second, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000))

    merged_first = list((first / "sources").glob("native_docs_*.pdf"))
    merged_second = list((second / "sources").glob("native_docs_*.pdf"))
    assert len(merged_first) == 1 and len(merged_second) == 1
    first_bytes = merged_first[0].read_bytes()
    second_bytes = merged_second[0].read_bytes()
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()
    assert b"/ID" not in first_bytes
    assert b"CreationDate (D" in first_bytes  # pinned date survives (colon escaped as \\072)
    assert b"D:20000101000000Z" not in first_bytes or b"D\\07220000101000000Z" in first_bytes


def test_packing_disabled_keeps_separate_natives(tmp_path: Path) -> None:
    chat, documents, scan_path = packed_chat(tmp_path)
    output = tmp_path / "out"
    build_package([chat], output, PackageConfig(source_limit=8, target_words=400_000, hard_words=500_000, pack_native_pdfs=False))


    sources = output / "sources"
    assert not list(sources.glob("native_docs_*.pdf"))
    natives = sorted(path.name for path in sources.iterdir() if path.name.startswith("native_"))
    assert len(natives) == 4  # three born-digital + one scanned, each single-slot
    assert all(name.endswith(".pdf") for name in natives)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    decisions = {record["name"]: record["decision"] for record in manifest["attachments"]}
    assert all(decisions[name] == "native_source" for name in ("one.pdf", "two.pdf", "three.pdf", "scan.pdf"))
