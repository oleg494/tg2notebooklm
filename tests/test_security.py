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


def test_resolve_export_path_rejects_backslash_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "..\\..\\secret.txt")


def test_resolve_export_path_rejects_percent_encoded_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "%2e%2e%2fsecret.txt")


def test_resolve_export_path_rejects_dot_segment_collapse(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "files/../evil.txt")


def test_resolve_export_path_rejects_empty_reference(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "")


def test_resolve_export_path_rejects_placeholder_reference(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_export_path(tmp_path, "(File not included)")


def test_safe_output_name_caps_length() -> None:
    from tg2notebooklm.security import safe_output_name

    long_name = "a" * 300 + ".pdf"
    assert len(safe_output_name(long_name)) <= 120
    assert safe_output_name(long_name).endswith(".pdf")
