from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


class UnsafePathError(ValueError):
    pass


def resolve_export_path(export_root: Path, reference: str) -> Path:
    """Resolve an untrusted Telegram path without allowing export-root escape."""
    if not reference or reference.startswith("("):
        raise UnsafePathError("reference is not a local file path")
    if "\x00" in reference:
        raise UnsafePathError(f"reference contains a NUL byte: {reference!r}")

    decoded = unquote(reference).replace("\\", "/")
    posix = PurePosixPath(decoded)
    if posix.is_absolute() or re.match(r"^[A-Za-z]:", decoded):
        raise UnsafePathError(f"absolute attachment path rejected: {reference}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise UnsafePathError(f"unsafe attachment path rejected: {reference}")

    root = export_root.resolve()
    try:
        candidate = root.joinpath(*posix.parts).resolve()
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"attachment escapes export root or is not a valid path: {reference}") from exc
    return candidate


def safe_slug(value: str, fallback: str = "chat", max_length: int = 72) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"[-_.]{2,}", "-", value).strip("-_.")
    return (value or fallback)[:max_length].rstrip("-_.") or fallback


def safe_output_name(name: str, fallback: str = "attachment") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).strip(" .")
    return cleaned or fallback
