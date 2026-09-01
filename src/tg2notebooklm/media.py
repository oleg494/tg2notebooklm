from __future__ import annotations

import hashlib
import math
import shutil
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFont, ImageOps
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from tg2notebooklm.model import Attachment, Chat, Message, PackageConfig
from tg2notebooklm.render import TEXT_ATTACHMENT_EXTENSIONS
from tg2notebooklm.security import safe_output_name

IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".ico", ".jp2", ".png", ".webp", ".tif", ".tiff",
    ".jpeg", ".jpg", ".jpe", ".heic", ".heif",
}
AUDIO_VIDEO_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aif", ".aifc", ".aiff", ".amr", ".au", ".avi",
    ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".ra", ".snd", ".wav", ".wma",
}
NATIVE_DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".csv", ".pptx", ".epub"}

ATLAS_FONT = "Tg2NotebookLMUnicode"


def _atlas_font() -> str:
    if ATLAS_FONT not in pdfmetrics.getRegisteredFontNames():
        font = ImageFont.load_default(size=12)
        stream = font.path
        stream.seek(0)
        pdfmetrics.registerFont(TTFont(ATLAS_FONT, stream))
    return ATLAS_FONT


@dataclass(slots=True)
class MediaCandidate:
    path: Path
    chat: Chat
    message: Message
    attachment: Attachment
    role: str = "primary"
    records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def suffix(self) -> str:
        return self.path.suffix.casefold()

    @property
    def display_name(self) -> str:
        if self.role == "thumbnail":
            return f"thumbnail for {self.attachment.name or self.attachment.kind}"
        return self.attachment.name or self.path.name


@dataclass(slots=True)
class AtlasResult:
    path: Path
    included: list[MediaCandidate]
    failed: list[tuple[MediaCandidate, str]]


def collect_candidates(chats: list[Chat]) -> tuple[list[MediaCandidate], list[dict[str, Any]]]:
    candidates_by_key: dict[tuple[Path, str], MediaCandidate] = {}
    records: list[dict[str, Any]] = []

    for chat in chats:
        root = chat.export_root
        for message in chat.messages:
            for attachment in message.attachments:
                relative_path = _relative_path(root, attachment.path)
                record: dict[str, Any] = {
                    "chat": chat.name,
                    "chat_id": chat.id,
                    "message_id": message.id,
                    "timestamp": message.timestamp,
                    "author": message.author,
                    "name": attachment.name,
                    "kind": attachment.kind,
                    "mime_type": attachment.mime_type,
                    "reference": attachment.reference,
                    "path": relative_path,
                    "available": attachment.available,
                    "reason": attachment.reason,
                    "declared_size": attachment.size,
                    "dimensions": [attachment.width, attachment.height] if attachment.width and attachment.height else None,
                    "duration_seconds": attachment.duration_seconds,
                    "decision": "pending" if attachment.available and attachment.path else "unavailable",
                }
                records.append(record)
                if attachment.available and attachment.path:
                    _add_candidate(candidates_by_key, attachment.path, chat, message, attachment, "primary", record)
                if attachment.thumbnail_path:
                    record["thumbnail_path"] = _relative_path(root, attachment.thumbnail_path)
                    record["thumbnail_decision"] = "pending"
                    _add_candidate(candidates_by_key, attachment.thumbnail_path, chat, message, attachment, "thumbnail", record)

    candidates = sorted(
        candidates_by_key.values(),
        key=lambda item: (item.message.sequence, item.chat.name.casefold(), str(item.path).casefold(), item.role),
    )
    return candidates, records


def classify_candidate(candidate: MediaCandidate, config: PackageConfig) -> str:
    suffix = candidate.suffix
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_VIDEO_EXTENSIONS:
        return "native"
    if suffix in NATIVE_DOCUMENT_EXTENSIONS:
        if suffix in TEXT_ATTACHMENT_EXTENSIONS and candidate.path.stat().st_size <= config.inline_text_max_bytes:
            return "inline_text"
        return "native"
    if suffix in TEXT_ATTACHMENT_EXTENSIONS and candidate.path.stat().st_size <= config.inline_text_max_bytes:
        return "inline_text"
    return "metadata_only"


def build_image_atlas(candidates: list[MediaCandidate], output_path: Path, config: PackageConfig) -> AtlasResult:
    page_size = LETTER if config.atlas_page_size.casefold() == "letter" else A4
    pdf = canvas.Canvas(str(output_path), pagesize=page_size, pageCompression=1, invariant=1)
    pdf.setTitle(output_path.stem)
    pdf.setAuthor("tg2notebooklm")
    width, height = page_size
    margin = 28.0
    caption_height = 48.0
    columns = 2 if config.images_per_page <= 8 else 3
    rows = max(1, math.ceil(config.images_per_page / columns))
    cell_width = (width - margin * 2) / columns
    cell_height = (height - margin * 2) / rows
    included: list[MediaCandidate] = []
    failed: list[tuple[MediaCandidate, str]] = []
    placed_on_page = 0

    for candidate in candidates:
        try:
            image_bytes, pixel_width, pixel_height = _normalized_image(candidate.path)
        except Exception as exc:
            failed.append((candidate, str(exc)))
            continue

        if placed_on_page == config.images_per_page:
            pdf.showPage()
            placed_on_page = 0
        row = placed_on_page // columns
        column = placed_on_page % columns
        x = margin + column * cell_width
        y = height - margin - (row + 1) * cell_height
        image_area_height = max(36.0, cell_height - caption_height)
        scale = min((cell_width - 12) / pixel_width, (image_area_height - 8) / pixel_height)
        draw_width = max(1.0, pixel_width * scale)
        draw_height = max(1.0, pixel_height * scale)
        image_x = x + (cell_width - draw_width) / 2
        image_y = y + caption_height + (image_area_height - draw_height) / 2
        pdf.drawImage(ImageReader(image_bytes), image_x, image_y, draw_width, draw_height, preserveAspectRatio=True, mask="auto")
        _draw_caption(pdf, candidate, x + 5, y + 6, cell_width - 10, caption_height - 8)
        included.append(candidate)
        placed_on_page += 1

    if included:
        pdf.save()
    else:
        pdf.save()
        output_path.unlink(missing_ok=True)
    return AtlasResult(output_path, included, failed)


def copy_native_source(candidate: MediaCandidate, output_dir: Path, ordinal: int) -> Path:
    digest = _file_digest(candidate.path)
    original_name = safe_output_name(candidate.path.name)
    target = output_dir / f"native_{ordinal:03d}__{digest}__{original_name}"
    shutil.copyfile(candidate.path, target)
    return target


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()[:8]


def mark_candidate(candidate: MediaCandidate, decision: str, *, source: str | None = None, reason: str | None = None) -> None:
    for record in candidate.records:
        key = "thumbnail_decision" if candidate.role == "thumbnail" else "decision"
        record[key] = decision
        if source:
            record["thumbnail_source" if candidate.role == "thumbnail" else "source"] = source
        if reason:
            record["thumbnail_reason" if candidate.role == "thumbnail" else "decision_reason"] = reason


def _add_candidate(
    candidates: dict[tuple[Path, str], MediaCandidate],
    path: Path,
    chat: Chat,
    message: Message,
    attachment: Attachment,
    role: str,
    record: dict[str, Any],
) -> None:
    resolved = path.resolve()
    key = (resolved, role)
    if key not in candidates:
        candidates[key] = MediaCandidate(resolved, chat, message, attachment, role)
    candidates[key].records.append(record)


def _relative_path(root: Path | None, path: Path | None) -> str | None:
    if path is None:
        return None
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _normalized_image(path: Path) -> tuple[BytesIO, int, int]:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image = image.convert("RGB")
        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True, progressive=True)
        output.seek(0)
        return output, image.width, image.height


def _draw_caption(pdf: canvas.Canvas, candidate: MediaCandidate, x: float, y: float, width: float, height: float) -> None:
    message = candidate.message
    lines = [
        f"{candidate.chat.name} | msg {message.id} | {message.timestamp or 'unknown date'}",
        f"{message.author or 'unknown author'} | {candidate.display_name}",
    ]
    if message.text.strip():
        lines.append(" ".join(message.text.split())[:220])
    font = _atlas_font()
    size = 6.5
    pdf.setFont(font, size)
    cursor = y + height - size
    for line in lines:
        for wrapped in _wrap_line(line, font, size, width):
            if cursor < y:
                return
            pdf.drawString(x, cursor, wrapped)
            cursor -= size + 1.5


def _wrap_line(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
