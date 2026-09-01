# Byte-deterministic packing of small born-digital PDFs into merged native sources (D8).

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from tg2notebooklm.media import _font, _pin_pdf_dates, _wrap

_COVER_DPI = 150  # matches the atlas rasterizer; 150/72 points per pixel
_LINE_SPACING = 4
_COVER_TEXT = (20, 20, 20)


def pypdf_available() -> bool:
    """Lazy probe: pypdf ships with the CLI install but not with the Pyodide wheel path."""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def _pdf_modules():
    from pypdf import PdfReader, PdfWriter

    return PdfReader, PdfWriter


@dataclass(slots=True)
class PdfPackItem:
    path: Path
    display_name: str
    chat_name: str
    message_id: str
    timestamp: str | None
    author: str | None


def has_text_layer(path: Path) -> bool:
    """True when any of the first pages carries extractable text (D8 scan gate).

    Corrupt/unparseable PDFs return False so they fall through to native copy
    instead of aborting the whole run (COR003).
    """
    try:
        PdfReader, _ = _pdf_modules()
        reader = PdfReader(path)
        try:
            return any((page.extract_text() or "").strip() for page in reader.pages[:3])
        finally:
            reader.stream.close()
    except Exception:
        return False

def merge_pdf_documents(items: list[PdfPackItem], output_path: Path) -> None:
    """Write one merged PDF: a provenance cover page followed by each document's pages.

    Determinism (D4): no /ID trailer, fixed metadata dates, no wall-clock
    timestamps anywhere in the output.
    """
    PdfReader, PdfWriter = _pdf_modules()
    writer = PdfWriter()
    with tempfile.TemporaryDirectory(prefix="tg2notebooklm-pdfpack-") as tmp:
        tmp_dir = Path(tmp)
        for ordinal, item in enumerate(items, start=1):
            cover = tmp_dir / f"cover_{ordinal:03d}.pdf"
            _write_cover_page(item, cover)
            writer.append(PdfReader(cover))
            writer.append(PdfReader(item.path))
    writer.add_metadata(
        {
            "/Creator": "tg2notebooklm",
            "/Producer": "tg2notebooklm",
            "/CreationDate": "D:20000101000000Z",
            "/ModDate": "D:20000101000000Z",
        }
    )
    with output_path.open("wb") as handle:
        writer.write(handle)
    _pin_pdf_dates(output_path)


def _write_cover_page(item: PdfPackItem, output_path: Path) -> None:
    """Rasterize a provenance cover page sized like the document's first page."""
    PdfReader, _ = _pdf_modules()
    reader = PdfReader(item.path)
    try:
        box = reader.pages[0].mediabox
        width = max(1.0, float(box.width))
        height = max(1.0, float(box.height))
    finally:
        reader.stream.close()
    pixel_w = max(1, round(width * _COVER_DPI / 72))
    pixel_h = max(1, round(height * _COVER_DPI / 72))
    image = Image.new("RGB", (pixel_w, pixel_h), "white")
    draw = ImageDraw.Draw(image)
    name_size = max(16, pixel_w // 16)
    line_size = max(11, pixel_w // 32)

    margin = max(8, pixel_w // 24)
    x = margin
    y = margin
    wrap_width = pixel_w - margin * 2
    draw.text((x, y), item.display_name, fill=_COVER_TEXT, font=_font(name_size))
    y += name_size + _LINE_SPACING * 2
    for text in (
        f"chat: {item.chat_name}",
        f"message: {item.message_id}",
        f"date: {item.timestamp or 'unknown'}",
        f"author: {item.author or 'unknown'}",
    ):
        for line in _wrap(text, line_size, wrap_width):
            draw.text((x, y), line, fill=_COVER_TEXT, font=_font(line_size))
            y += line_size + _LINE_SPACING
    image.save(output_path, "PDF", resolution=_COVER_DPI)
    _pin_pdf_dates(output_path)
