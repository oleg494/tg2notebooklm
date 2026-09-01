from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from tg2notebooklm.model import Chat, PackageConfig

AUDIO_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aif", ".aifc", ".aiff", ".amr", ".au", ".avi",
    ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".ra", ".snd", ".wav", ".wma",
}
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".heic", ".heif", ".ico", ".jp2", ".jpe", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def enrich_chats(chats: list[Chat], config: PackageConfig) -> list[str]:
    warnings: list[str] = []
    if config.transcribe_audio:
        warnings.extend(_transcribe_audio(chats, config))
    if config.ocr_images:
        warnings.extend(_ocr_images(chats, config))
    return warnings


def _transcribe_audio(chats: list[Chat], config: PackageConfig) -> list[str]:
    warnings: list[str] = []
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        return ["Audio transcription requested, but faster-whisper is not installed. Install tg2notebooklm[transcribe]."]

    try:
        model: Any = WhisperModel(config.whisper_model, device="auto", compute_type="auto")
    except Exception as exc:  # external model/runtime failure
        return [f"Audio transcription model could not be loaded: {exc}"]

    processed = 0
    seen: dict[Path, str] = {}
    for chat in chats:
        for message in chat.messages:
            for attachment in message.attachments:
                path = attachment.path
                if not attachment.available or path is None or path.suffix.casefold() not in AUDIO_EXTENSIONS:
                    continue
                if config.enrichment_max_files and processed >= config.enrichment_max_files:
                    return warnings + [f"Enrichment stopped at configured limit ({config.enrichment_max_files} files)."]
                if path in seen:
                    transcript = seen[path]
                else:
                    try:
                        segments, info = model.transcribe(str(path), language=config.whisper_language, vad_filter=True)
                        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
                        if transcript:
                            transcript = f"[Local transcript; language={getattr(info, 'language', 'unknown')}] {transcript}"
                        else:
                            warnings.append(f"No speech detected in {path.name}")
                    except Exception as exc:
                        warnings.append(f"Could not transcribe {path.name}: {exc}")
                        transcript = ""
                    seen[path] = transcript
                    processed += 1
                if transcript:
                    message.text = f"{message.text}\n\n{transcript}".strip()
                    attachment.metadata["transcribed_locally"] = True
    return warnings


def _ocr_images(chats: list[Chat], config: PackageConfig) -> list[str]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return ["Image OCR requested, but the tesseract executable is not available on PATH."]

    warnings: list[str] = []
    processed = 0
    seen: dict[Path, str] = {}
    for chat in chats:
        for message in chat.messages:
            for attachment in message.attachments:
                path = attachment.path
                if not attachment.available or path is None or path.suffix.casefold() not in IMAGE_EXTENSIONS:
                    continue
                if config.enrichment_max_files and processed >= config.enrichment_max_files:
                    return warnings + [f"Enrichment stopped at configured limit ({config.enrichment_max_files} files)."]
                if path in seen:
                    ocr_text = seen[path]
                else:
                    try:
                        ocr_text = _run_tesseract(tesseract, path, config.ocr_languages)
                    except Exception as exc:
                        warnings.append(f"Could not OCR {path.name}: {exc}")
                        ocr_text = ""
                    seen[path] = ocr_text
                    processed += 1
                if ocr_text:
                    message.text = f"{message.text}\n\n[Local image OCR] {ocr_text}".strip()
                    attachment.metadata["ocr_locally"] = True
    return warnings


def _run_tesseract(executable: str, image_path: Path, languages: str) -> str:
    with tempfile.TemporaryDirectory(prefix="tg2notebooklm-ocr-") as temp_dir:
        normalized = Path(temp_dir) / "image.png"
        with Image.open(image_path) as image:
            image.convert("RGB").save(normalized)
        completed = subprocess.run(
            [executable, str(normalized), "stdout", "-l", languages],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    return " ".join(completed.stdout.split())
