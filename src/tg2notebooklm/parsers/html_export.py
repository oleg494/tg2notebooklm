from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from tg2notebooklm.model import Attachment, Chat, Message, Poll, PollAnswer, Reaction
from tg2notebooklm.security import UnsafePathError, resolve_export_path

PAGE_RE = re.compile(r"^messages(?:(\d+))?\.html$", re.IGNORECASE)
MESSAGE_ID_RE = re.compile(r"message(-?\d+)$")
REPLY_ID_RE = re.compile(r"message(-?\d+)$")


def parse_html_export(path: Path) -> Chat:
    root = Path(path)
    if root.is_file():
        root = root.parent
    pages = _html_pages(root)
    if not pages:
        raise ValueError("No messages*.html files found")

    messages: list[Message] = []
    current_author: str | None = None
    chat_name = "Telegram chat"
    sequence = 0
    for page_index, page in enumerate(pages):
        soup = BeautifulSoup(page.read_text(encoding="utf-8-sig"), "html.parser")
        if page_index == 0:
            heading = soup.select_one(".page_header .text")
            if heading:
                chat_name = heading.get_text(" ", strip=True) or chat_name
        for node in soup.select("div.history > div.message"):
            classes = set(node.get("class", []))
            message_id = _message_id(node.get("id"), sequence)
            if "service" in classes:
                messages.append(_parse_service(node, message_id, sequence))
                sequence += 1
                continue
            if "default" not in classes:
                continue
            author_node = _direct_child(node, "div", "body")
            from_node = _direct_child(author_node, "div", "from_name") if author_node else None
            if from_node:
                current_author = from_node.get_text(" ", strip=True) or current_author
            message = _parse_default(node, message_id, sequence, current_author, root)
            messages.append(message)
            sequence += 1

    return Chat(name=chat_name, kind="chat", id=None, input_format="html", messages=messages, export_root=root.resolve())


def _html_pages(root: Path) -> list[Path]:
    pages = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        match = PAGE_RE.match(path.name)
        if match:
            number = int(match.group(1) or 1)
            pages.append((number, path.name.casefold(), path))
    return [item[2] for item in sorted(pages)]


def _parse_service(node: Tag, message_id: str, sequence: int) -> Message:
    body = node.select_one(".body")
    text = body.get_text(" ", strip=True) if body else ""
    is_date = bool(re.fullmatch(r"\d{1,2}\s+\w+\s+\d{4}", text, flags=re.UNICODE))
    return Message(
        id=message_id,
        sequence=sequence,
        kind="date_marker" if is_date else "service",
        text=text,
        service_action="date_marker" if is_date else "html_service",
    )


def _parse_default(node: Tag, message_id: str, sequence: int, author: str | None, root: Path) -> Message:
    outer_body = _direct_child(node, "div", "body")
    timestamp_node = _direct_child(outer_body, "div", "date") if outer_body else None
    timestamp = timestamp_node.get("title") if timestamp_node else None
    reply_to = None
    reply_node = _direct_child(outer_body, "div", "reply_to") if outer_body else None
    if reply_node:
        link = reply_node.find("a", href=True)
        if link:
            match = REPLY_ID_RE.search(str(link.get("href")))
            reply_to = match.group(1) if match else None

    forwarded = _direct_child(outer_body, "div", "body", required_classes={"forwarded"}) if outer_body else None
    content_body = forwarded or outer_body
    forwarded_from = None
    forwarded_date = None
    if forwarded:
        forwarded_name = _direct_child(forwarded, "div", "from_name")
        if forwarded_name:
            clone = BeautifulSoup(str(forwarded_name), "html.parser")
            for date in clone.select(".date"):
                forwarded_date = date.get("title") or date.get_text(" ", strip=True)
                date.decompose()
            forwarded_from = clone.get_text(" ", strip=True)

    text_node = _direct_child(content_body, "div", "text") if content_body else None
    text = _html_fragment_to_markdown(text_node) if text_node else ""
    poll = _parse_html_poll(content_body)
    attachments = _parse_html_attachments(content_body, root, message_id) + _parse_html_media_wraps(content_body, root, message_id)
    reactions = _parse_html_reactions(outer_body)
    inline_buttons: list[dict[str, Any]] = []
    button_table = _direct_child(outer_body, "table", "bot_buttons_table") if outer_body else None
    if button_table:
        inline_buttons = [{"text": button.get_text(" ", strip=True)} for button in button_table.select(".bot_button")]

    return Message(
        id=message_id,
        sequence=sequence,
        kind="message",
        timestamp=str(timestamp) if timestamp else None,
        author=author,
        text=text,
        forwarded_date=forwarded_date,
        reply_to_id=reply_to,
        forwarded_from=forwarded_from,
        reactions=reactions,
        attachments=attachments,
        poll=poll,
        inline_buttons=inline_buttons,
    )


def _parse_html_reactions(body: Tag | None) -> list[Reaction]:
    if body is None:
        return []
    reactions = []
    for node in body.select(":scope > .reactions > .reaction"):
        emoji_node = node.select_one(".emoji")
        count_node = node.select_one(".count")
        emoji = emoji_node.get_text(" ", strip=True) if emoji_node else "reaction"
        reactors = [initials.get("title") for initials in node.select(".userpics .initials[title]") if initials.get("title")]
        count = _parse_int(count_node.get_text(" ", strip=True) if count_node else None) or max(1, len(reactors))
        reactions.append(Reaction(value=emoji, count=count, recent=[{"from": name} for name in reactors]))
    return reactions


def _parse_html_poll(body: Tag | None) -> Poll | None:
    poll_node = _direct_child(body, "div", "media_wrap") if body else None
    poll_node = poll_node.select_one(".media_poll") if poll_node else None
    if poll_node is None:
        return None
    question_node = poll_node.select_one(".question")
    question = question_node.get_text(" ", strip=True) if question_node else "Poll"
    answers = [PollAnswer(text=answer.get_text(" ", strip=True)) for answer in poll_node.select(".answer")]
    total_node = poll_node.select_one(".total")
    total = _parse_int(total_node.get_text(" ", strip=True) if total_node else None)
    return Poll(question=question, answers=answers, total_voters=total)


def _parse_html_attachments(body: Tag | None, root: Path, message_id: str) -> list[Attachment]:
    if body is None:
        return []
    attachments: list[Attachment] = []
    seen: set[tuple[str | None, str]] = set()
    for media in body.select(":scope > .media_wrap .media"):
        classes = set(media.get("class", []))
        kind = next((item.removeprefix("media_") for item in classes if item.startswith("media_") and item not in {"media_wrap"}), "file")
        href = media.get("href") if media.name == "a" else None
        title_node = media.select_one(".title")
        description_node = media.select_one(".description")
        status_node = media.select_one(".status")
        name = title_node.get_text(" ", strip=True) if title_node else kind
        description = description_node.get_text(" ", strip=True) if description_node else None
        status = status_node.get_text(" ", strip=True) if status_node else None
        key = (str(href) if href else None, kind)
        if key in seen:
            continue
        seen.add(key)
        path = None
        available = False
        reason = None
        reference = str(href) if href else None
        if reference and reference.startswith("files/"):
            try:
                candidate = resolve_export_path(root, reference)
                if candidate.is_file():
                    path, available = candidate, True
                else:
                    reason = "Referenced file is missing from export"
            except UnsafePathError as exc:
                reason = str(exc)
        else:
            reason = status or description or "File not included in HTML export"
        attachments.append(
            Attachment(
                reference=reference,
                path=path,
                name=name or (path.name if path else kind),
                kind=kind,
                available=available,
                reason=reason,
                message_id=message_id,
                metadata={key: value for key, value in {"description": description, "status": status}.items() if value},
            )
        )
    return attachments

def _parse_html_media_wraps(body: Tag | None, root: Path, message_id: str) -> list[Attachment]:
    """Parse photo_wrap/sticker_wrap blocks present when HTML export downloaded media."""
    if body is None:
        return []
    attachments: list[Attachment] = []
    seen: set[str | None] = set()
    for wrap in body.select(":scope > .photo_wrap, :scope > .sticker_wrap"):
        classes = set(wrap.get("class", []))
        kind = "sticker" if "sticker_wrap" in classes else "photo"
        anchor = wrap.find("a", href=True)
        image = wrap.find("img", src=True)
        raw_reference = None
        if anchor is not None:
            raw_reference = anchor.get("href")
        elif image is not None:
            raw_reference = image.get("src")
        reference = str(raw_reference) if raw_reference else None
        if reference in seen:
            continue
        seen.add(reference)
        path = None
        available = False
        reason = None
        if reference:
            try:
                candidate = resolve_export_path(root, reference)
                if candidate.is_file():
                    path, available = candidate, True
                else:
                    reason = "Referenced file is missing from export"
            except UnsafePathError as exc:
                reason = str(exc)
        else:
            reason = "Downloaded media block has no file reference"
        title = anchor.get("title") if anchor is not None else None
        attachments.append(
            Attachment(
                reference=reference,
                path=path,
                name=(path.name if path else (title or kind)),
                kind=kind,
                available=available,
                reason=reason,
                message_id=message_id,
            )
        )
    return attachments


def _html_fragment_to_markdown(node: Tag) -> str:
    return _render_html_children(node).strip()


def _render_html_children(node: Tag) -> str:
    return "".join(_render_html_item(child) for child in node.children)


def _render_html_item(item: Tag | NavigableString) -> str:
    if isinstance(item, NavigableString):
        return html.unescape(str(item))
    if not isinstance(item, Tag):
        return ""
    name = item.name.lower()
    content = _render_html_children(item)
    if name == "br":
        return "\n"
    if name in {"strong", "b"}:
        return f"**{content}**"
    if name in {"em", "i"}:
        return f"*{content}*"
    if name == "u":
        return f"<u>{content}</u>"
    if name in {"s", "strike", "del"}:
        return f"~~{content}~~"
    if name == "code":
        return f"`{content.replace('`', 'ˋ')}`"
    if name == "pre":
        return f"\n```\n{item.get_text()}\n```\n"
    if name == "blockquote":
        return "\n" + "\n".join(f"> {line}" for line in item.get_text("\n").splitlines()) + "\n"
    if name == "a":
        href = str(item.get("href") or "")
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https", "mailto"}:
            return f"[{content}]({href})"
        return content
    return content


def _direct_child(parent: Tag | None, tag: str, class_name: str, *, required_classes: set[str] | None = None) -> Tag | None:
    if parent is None:
        return None
    required = required_classes or set()
    for child in parent.find_all(tag, recursive=False):
        classes = set(child.get("class", []))
        if class_name in classes and required.issubset(classes):
            return child
    return None


def _message_id(raw: Any, sequence: int) -> str:
    match = MESSAGE_ID_RE.match(str(raw or ""))
    return match.group(1) if match else f"html-{sequence}"


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value.replace(" ", ""))
    return int(match.group(0)) if match else None
