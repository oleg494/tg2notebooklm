from pathlib import Path

import pytest

from tg2notebooklm.security import UnsafePathError, resolve_export_path


def test_resolve_export_path_accepts_contained_file(tmp_path: Path) -> None:
    file = tmp_path / "files" / "note.txt"
    file.parent.mkdir()
    file.write_text("ok", encoding="utf-8")

    assert resolve_export_path(tmp_path, "files/note.txt") == file.resolve()


def test_resolve_export_path_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "../secret.txt")


def test_resolve_export_path_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "C:/Windows/win.ini")
