from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Reaction:
    value: str
    count: int = 1
    kind: str = "emoji"
    recent: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Attachment:
    reference: str | None = None
    path: Path | None = None
    name: str | None = None
    kind: str = "file"
    mime_type: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None
    available: bool = False
    reason: str | None = None
    message_id: str | None = None
    thumbnail_reference: str | None = None
    thumbnail_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PollAnswer:
    text: str
    voters: int | None = None
    chosen: bool | None = None


@dataclass(slots=True)
class Poll:
    question: str
    answers: list[PollAnswer] = field(default_factory=list)
    total_voters: int | None = None
    closed: bool | None = None


@dataclass(slots=True)
class Message:
    id: str
    sequence: int
    kind: str
    timestamp: str | None = None
    timestamp_unix: int | None = None
    author: str | None = None
    author_id: str | None = None
    text: str = ""
    reply_to_id: str | None = None
    reply_to_peer_id: str | None = None
    forwarded_from: str | None = None
    forwarded_from_id: str | None = None
    saved_from: str | None = None
    forwarded_date: str | None = None
    edited_at: str | None = None
    reactions: list[Reaction] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    service_action: str | None = None
    service_details: dict[str, Any] = field(default_factory=dict)
    poll: Poll | None = None
    topic_id: str | None = None
    topic_title: str | None = None
    via_bot: str | None = None
    inline_buttons: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Chat:
    name: str
    kind: str
    id: str | None
    input_format: str
    messages: list[Message] = field(default_factory=list)
    export_root: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PackageConfig:
    source_limit: int = 50
    target_words: int = 400_000
    hard_words: int = 500_000
    max_source_bytes: int = 190 * 1024 * 1024
    images_per_page: int = 8
    images_per_atlas: int = 160
    atlas_page_size: str = "A4"
    inline_text_max_bytes: int = 2 * 1024 * 1024
    include_native_files: bool = True
    include_image_atlases: bool = True
    pack_native_pdfs: bool = True
    pdf_pack_max_mb: int = 20
    docs_to_markdown: bool = False
    docs_pack_max_mb: int = 20
    transcribe_audio: bool = False
    whisper_model: str = "small"
    whisper_language: str | None = None
    ocr_images: bool = False
    ocr_languages: str = "eng+rus"
    enrichment_max_files: int = 0
    force: bool = False

    def validate(self) -> None:
        if self.source_limit < 2:
            raise ValueError("source_limit must be at least 2 (index + content)")
        if self.target_words < 1 or self.hard_words < 1:
            raise ValueError("word limits must be positive")
        if self.target_words > self.hard_words:
            raise ValueError("target_words cannot exceed hard_words")
        if self.hard_words > 500_000:
            raise ValueError("hard_words cannot exceed Gemini Notebook's 500,000-word limit")
        if self.max_source_bytes < 1 or self.max_source_bytes > 200 * 1024 * 1024:
            raise ValueError("max_source_bytes must be between 1 byte and Gemini Notebook's 200 MB ceiling")
        if self.inline_text_max_bytes < 0:
            raise ValueError("inline_text_max_bytes cannot be negative")
        if self.enrichment_max_files < 0:
            raise ValueError("enrichment_max_files cannot be negative")
        if self.images_per_page < 1 or self.images_per_atlas < 1:
            raise ValueError("image packing values must be positive")
        if self.pdf_pack_max_mb < 1:
            raise ValueError("pdf_pack_max_mb must be at least 1 MB")
        if self.pdf_pack_max_mb * 1024 * 1024 > self.max_source_bytes:
            raise ValueError("pdf_pack_max_mb cannot exceed the max_source_bytes ceiling")
        if self.docs_pack_max_mb < 1:
            raise ValueError("docs_pack_max_mb must be at least 1 MB")
        if self.docs_pack_max_mb * 1024 * 1024 > self.max_source_bytes:
            raise ValueError("docs_pack_max_mb cannot exceed the max_source_bytes ceiling")


@dataclass(slots=True)
class PackageResult:
    output_dir: Path
    source_count: int
    attachment_catalog_count: int
    text_source_count: int
    image_atlas_count: int
    native_source_count: int
    message_count: int
    attachment_count: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "source_count": self.source_count,
            "text_source_count": self.text_source_count,
            "attachment_catalog_count": self.attachment_catalog_count,
            "image_atlas_count": self.image_atlas_count,
            "native_source_count": self.native_source_count,
            "message_count": self.message_count,
            "attachment_count": self.attachment_count,
            "warnings": self.warnings,
        }
