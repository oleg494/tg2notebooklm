"""Universal file-dump parser (D10): turn any folder of files into a Chat.

Every regular file becomes one Message with a metadata-only Attachment; the
existing packing lanes (inline text, docs-to-markdown, PDF packing, image
atlases, native copies) do the rest. Deterministic: files are sorted by
posix-style relative path casefolded, and no filesystem timestamps are read.
"""
from __future__ import annotations

from pathlib import Path

from tg2notebooklm.model import Attachment, Chat, Message

SKIP_DIRECTORIES = {"__pycache__", ".git", ".hg", ".svn", "node_modules", "__macosx"}
SKIP_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
MAX_FILES = 20_000


def _skipped(path: Path) -> bool:
    if path.suffix.casefold() in SKIP_SUFFIXES:
        return True
    if path.name.casefold() in SKIP_FILENAMES:
        return True
    return any(part.casefold() in SKIP_DIRECTORIES for part in path.parts)


def parse_file_dump(path: Path) -> Chat:
    root = Path(path)
    if root.is_file():
        root = root.parent
    if not root.is_dir():
        raise FileNotFoundError(path)

    messages: list[Message] = []
    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and not _skipped(p)),
        key=lambda p: p.relative_to(root).as_posix().casefold(),
    )
    if len(files) > MAX_FILES:
        raise ValueError(
            f"Folder contains {len(files):,} files (cap {MAX_FILES:,}); split it into smaller dumps."
        )

    for sequence, file_path in enumerate(files, start=1):
        relative = file_path.relative_to(root).as_posix()
        try:
            size = file_path.stat().st_size
        except OSError:
            size = None
        messages.append(
            Message(
                id=f"file-{sequence:06d}",
                sequence=sequence,
                kind="message",
                timestamp=None,
                author=None,
                text="",
                attachments=[
                    Attachment(
                        reference=relative,
                        path=file_path,
                        name=file_path.name,
                        kind="file",
                        size=size,
                        available=True,
                    )
                ],
            )
        )

    return Chat(
        name=root.resolve().name or "file-dump",
        kind="folder_dump",
        id=None,
        input_format="file_dump",
        messages=messages,
        export_root=root,
    )
