# Opt-in conversion of small office documents into Markdown, packed into shared
# docs_*.md sources (D8 rule 2). Mirrors pdfpack's lazy-import pattern so the
# Pyodide wheel path (no markitdown) degrades gracefully.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tg2notebooklm.render import code_fence_for, count_words

DOC_EXTENSIONS = {".docx", ".pptx", ".epub"}


def markitdown_available() -> bool:
    """Lazy probe: markitdown ships with the [docs] extra but not with the CLI or Pyodide wheel path."""
    try:
        import markitdown  # noqa: F401
    except ImportError:
        return False
    return True


def _doc_modules():
    from markitdown import MarkItDown

    return MarkItDown


@dataclass(slots=True)
class DocPackItem:
    path: Path
    display_name: str
    chat_name: str
    message_id: str
    timestamp: str | None
    author: str | None
    markdown: str


def convert_to_markdown(path: Path) -> str | None:
    """Convert one office document to Markdown; None on any failure (caller falls back to native)."""
    try:
        MarkItDown = _doc_modules()
        result = MarkItDown().convert(str(path))
        markdown = result.text_content
        if not markdown or not markdown.strip():
            return None
        return markdown
    except Exception:
        return None


def render_document_section(item: DocPackItem, ordinal: int, file_size: int) -> str:
    """One boundary-delimited section: header, provenance lines, fenced converted body."""
    fence = code_fence_for(item.markdown)
    lines = [
        f"# doc-{ordinal:02d}: {item.display_name}",
        "",
        f"- chat: {item.chat_name}",
        f"- message id: {item.message_id}",
        f"- date: {item.timestamp or 'unknown'}",
        f"- author: {item.author or 'unknown'}",
        f"- original file: {item.display_name} ({file_size:,} bytes)",
        "",
        fence,
        item.markdown.rstrip(),
        fence,
    ]
    return "\n".join(lines) + "\n"


def pack_documents(items: list[DocPackItem], hard_words: int) -> list[str]:
    """Greedily group rendered sections into source contents, each within hard_words."""
    contents: list[str] = []
    parts: list[str] = []
    words = 0
    for ordinal, item in enumerate(items, start=1):
        size = item.path.stat().st_size
        section = render_document_section(item, ordinal, size)
        section_words = count_words(section)
        if parts and words + section_words > hard_words:
            contents.append("\n".join(parts).rstrip() + "\n")
            parts = []
            words = 0
        parts.append(section)
        words += section_words
    if parts:
        contents.append("\n".join(parts).rstrip() + "\n")
    return contents
