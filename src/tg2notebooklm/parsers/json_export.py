from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tg2notebooklm.model import Attachment, Chat, Message, Poll, PollAnswer, Reaction
from tg2notebooklm.security import UnsafePathError, resolve_export_path

KNOWN_MESSAGE_KEYS = {
    "id", "type", "date", "date_unixtime", "from", "from_id", "actor", "actor_id",
    "text", "text_entities", "reply_to_message_id", "reply_to_peer_id", "forwarded_from",
    "forwarded_from_id", "forwarded_date", "saved_from", "edited", "edited_unixtime", "reactions", "photo",
    "photo_file_size", "file", "file_name", "file_size", "mime_type", "thumbnail",
    "thumbnail_file_size", "media_type", "duration_seconds", "width", "height", "sticker_emoji",
    "media_spoiler", "performer", "title", "via_bot", "inline_bot_buttons", "poll",
    "rich_message", "action", "inviter", "members", "new_title", "new_icon_emoji_id",
}

PLACEHOLDER_PREFIX = "(File "


def parse_json_export(path: Path) -> list[Chat]:
    path = Path(path)
    if path.is_dir():
        path = path / "result.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Telegram result.json must contain an object")

    if isinstance(data.get("messages"), list):
        raw_chats = [data]
    else:
        chats = data.get("chats")
        raw_chats = chats.get("list", []) if isinstance(chats, dict) else []
    if not raw_chats:
        raise ValueError("No Telegram chats found in result.json")

    export_root = path.parent.resolve()
    return [_parse_chat(raw, export_root) for raw in raw_chats if isinstance(raw, dict)]


def _parse_chat(raw: dict[str, Any], export_root: Path) -> Chat:
    messages = [_parse_message(item, index, export_root) for index, item in enumerate(raw.get("messages", [])) if isinstance(item, dict)]
    chat = Chat(
        name=str(raw.get("name") or "Telegram chat"),
        kind=str(raw.get("type") or "chat"),
        id=_string_or_none(raw.get("id")),
        input_format="json",
        messages=messages,
        export_root=export_root,
        extra={key: value for key, value in raw.items() if key not in {"name", "type", "id", "messages"}},
    )
    _assign_topics(chat)
    return chat


def _parse_message(raw: dict[str, Any], sequence: int, export_root: Path) -> Message:
    kind = str(raw.get("type") or "message")
    author = raw.get("from") if kind == "message" else raw.get("actor")
    author_id = raw.get("from_id") if kind == "message" else raw.get("actor_id")
    message_id = _string_or_none(raw.get("id")) or f"sequence-{sequence}"
    message = Message(
        id=message_id,
        sequence=sequence,
        kind=kind,
        timestamp=_string_or_none(raw.get("date")),
        timestamp_unix=_int_or_none(raw.get("date_unixtime")),
        author=_string_or_none(author),
        author_id=_string_or_none(author_id),
        text=_message_text(raw),
        reply_to_id=_string_or_none(raw.get("reply_to_message_id")),
        reply_to_peer_id=_string_or_none(raw.get("reply_to_peer_id")),
        forwarded_from=_string_or_none(raw.get("forwarded_from")),
        forwarded_from_id=_string_or_none(raw.get("forwarded_from_id")),
        saved_from=_string_or_none(raw.get("saved_from")),
        forwarded_date=_string_or_none(raw.get("forwarded_date")),
        edited_at=_string_or_none(raw.get("edited")),
        reactions=_parse_reactions(raw.get("reactions")),
        service_action=_string_or_none(raw.get("action")),
        service_details=_service_details(raw),
        poll=_parse_poll(raw.get("poll")),
        via_bot=_string_or_none(raw.get("via_bot")),
        inline_buttons=_parse_inline_buttons(raw.get("inline_bot_buttons")),
        extra={key: value for key, value in raw.items() if key not in KNOWN_MESSAGE_KEYS},
    )
    message.attachments = _parse_attachments(raw, export_root, message_id)
    return message


def _message_text(raw: dict[str, Any]) -> str:
    entities = raw.get("text_entities")
    text = raw.get("text")
    if isinstance(entities, list) and entities:
        return _render_entities(entities)
    if isinstance(text, list):
        return _render_entities(text)
    if isinstance(text, str):
        return text
    rich = raw.get("rich_message")
    return _render_rich_message(rich) if isinstance(rich, dict) else ""


def _render_entities(parts: Iterable[Any]) -> str:
    return "".join(_render_entity(part) if isinstance(part, dict) else str(part) for part in parts)


def _render_entity(entity: dict[str, Any]) -> str:
    kind = str(entity.get("type") or "plain")
    text = str(entity.get("text") or "")
    if kind == "bold":
        return f"**{text}**"
    if kind == "italic":
        return f"*{text}*"
    if kind == "underline":
        return f"<u>{text}</u>"
    if kind == "strikethrough":
        return f"~~{text}~~"
    if kind == "spoiler":
        return f"<span data-telegram-spoiler=\"true\">{text}</span>"
    if kind == "code":
        return f"`{text.replace('`', 'ˋ')}`"
    if kind == "pre":
        language = str(entity.get("language") or "")
        return f"\n```{language}\n{text}\n```\n"
    if kind == "blockquote":
        return "\n" + "\n".join(f"> {line}" for line in text.splitlines()) + "\n"
    if kind == "text_link":
        href = str(entity.get("href") or "")
        return f"[{text}]({href})" if href else text
    if kind == "mention_name":
        user_id = entity.get("user_id")
        return f"{text} [telegram-user:{user_id}]" if user_id is not None else text
    if kind == "custom_emoji":
        document_id = entity.get("document_id")
        return f"{text}<!-- custom_emoji:{document_id} -->" if document_id else text
    return text


def _render_rich_message(rich: dict[str, Any]) -> str:
    return "\n\n".join(filter(None, (_render_rich_block(block) for block in rich.get("blocks", []) if isinstance(block, dict))))


def _render_rich_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value:
            text = value.get("text")
            if isinstance(text, list):
                return _render_entities(text)
            if isinstance(text, dict):
                return _render_rich_text(text)
            if isinstance(text, str):
                return _render_entity(value) if value.get("type") not in {None, "plain"} else text
        if value.get("type") == "anchor":
            return ""
    if isinstance(value, list):
        return "".join(_render_rich_text(item) for item in value)
    return ""


def _render_rich_block(block: dict[str, Any]) -> str:
    kind = block.get("type")
    if kind == "paragraph":
        return _render_rich_text(block.get("text"))
    if kind == "heading":
        level = min(max(_int_or_none(block.get("level")) or 2, 1), 6)
        return f"{'#' * level} {_render_rich_text(block.get('text'))}"
    if kind == "divider":
        return "---"
    if kind == "footer":
        return f"_Footer: {_render_rich_text(block.get('text'))}_"
    if kind == "list":
        lines = []
        for item in block.get("items", []):
            if not isinstance(item, dict):
                continue
            content = _render_rich_text(item.get("text") or item.get("content"))
            prefix = "1." if block.get("kind") == "ordered" else "-"
            lines.append(f"{prefix} {content}")
        return "\n".join(lines)
    if kind == "table":
        rows = block.get("rows", [])
        rendered = []
        for row in rows:
            cells = row.get("cells", []) if isinstance(row, dict) else []
            rendered.append("| " + " | ".join(_render_rich_text(cell) for cell in cells) + " |")
        if rendered:
            width = rendered[0].count("|") - 1
            rendered.insert(1, "|" + " --- |" * max(width, 1))
        return "\n".join(rendered)
    if kind == "details":
        title = _render_rich_text(block.get("title")) or "Details"
        body = "\n\n".join(_render_rich_block(item) for item in block.get("blocks", []) if isinstance(item, dict))
        return f"### {title}\n\n{body}"
    if kind == "collage":
        caption = _render_rich_text(block.get("caption"))
        items = "\n".join(_render_rich_block(item) for item in block.get("items", []) if isinstance(item, dict))
        return f"{caption}\n{items}".strip()
    if kind in {"photo", "video"}:
        caption = _render_rich_text(block.get("caption"))
        name = block.get("file_name") or block.get("photo_id") or kind
        reason = block.get("file_skip_reason") or block.get("photo_skip_reason") or "not exported"
        return f"[{kind}: {name}; {reason}]" + (f" {caption}" if caption else "")
    return f"[unsupported rich block: {kind}]"


def _parse_reactions(value: Any) -> list[Reaction]:
    reactions: list[Reaction] = []
    if not isinstance(value, list):
        return reactions
    for raw in value:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "emoji")
        display = raw.get("emoji") if kind == "emoji" else f"custom:{raw.get('document_id')}"
        reactions.append(Reaction(value=str(display or "reaction"), count=_int_or_none(raw.get("count")) or 1, kind=kind, recent=list(raw.get("recent") or [])))
    return reactions


def _parse_poll(value: Any) -> Poll | None:
    if not isinstance(value, dict):
        return None
    answers = []
    for answer in value.get("answers", []):
        if isinstance(answer, dict):
            answers.append(PollAnswer(text=str(answer.get("text") or ""), voters=_int_or_none(answer.get("voters")), chosen=answer.get("chosen") if isinstance(answer.get("chosen"), bool) else None))
    return Poll(question=str(value.get("question") or ""), answers=answers, total_voters=_int_or_none(value.get("total_voters")), closed=value.get("closed") if isinstance(value.get("closed"), bool) else None)


def _parse_attachments(raw: dict[str, Any], export_root: Path, message_id: str) -> list[Attachment]:
    attachments: list[Attachment] = []
    if "photo" in raw:
        attachments.append(_attachment_from_reference(raw, "photo", "photo", export_root, message_id, size_key="photo_file_size"))
    if "file" in raw:
        kind = str(raw.get("media_type") or "document")
        attachments.append(_attachment_from_reference(raw, "file", kind, export_root, message_id, size_key="file_size"))
    return attachments


def _attachment_from_reference(raw: dict[str, Any], key: str, kind: str, export_root: Path, message_id: str, *, size_key: str) -> Attachment:
    value = raw.get(key)
    reference = value if isinstance(value, str) else None
    reason = None
    path = None
    available = False
    if reference:
        if reference.startswith(PLACEHOLDER_PREFIX):
            reason = reference.strip("()")
        else:
            try:
                candidate = resolve_export_path(export_root, reference)
                if candidate.is_file():
                    path, available = candidate, True
                else:
                    reason = "Referenced file is missing from export"
            except UnsafePathError as exc:
                reason = str(exc)
    else:
        reason = "Telegram export did not include a local path"

    thumbnail_reference = raw.get("thumbnail") if isinstance(raw.get("thumbnail"), str) else None
    thumbnail_path = None
    if thumbnail_reference and not thumbnail_reference.startswith(PLACEHOLDER_PREFIX):
        try:
            candidate = resolve_export_path(export_root, thumbnail_reference)
            if candidate.is_file():
                thumbnail_path = candidate
        except UnsafePathError:
            pass


    return Attachment(
        reference=reference,
        path=path,
        name=_string_or_none(raw.get("file_name")) or (path.name if path else kind),
        kind=kind,
        mime_type=_string_or_none(raw.get("mime_type")),
        size=_int_or_none(raw.get(size_key)),
        width=_int_or_none(raw.get("width")),
        height=_int_or_none(raw.get("height")),
        duration_seconds=_int_or_none(raw.get("duration_seconds")),
        available=available,
        reason=reason,
        message_id=message_id,
        thumbnail_reference=thumbnail_reference,
        thumbnail_path=thumbnail_path,
        metadata={
            key: raw[key]
            for key in ("sticker_emoji", "media_spoiler", "performer", "title")
            if key in raw
        },
    )
def _parse_inline_buttons(value: Any) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return buttons
    for row in value:
        if not isinstance(row, list):
            continue
        for button in row:
            if isinstance(button, dict):
                buttons.append({key: button[key] for key in ("text", "type", "data") if key in button})
    return buttons



def _service_details(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: raw[key] for key in ("inviter", "members", "title", "new_title", "new_icon_emoji_id") if key in raw}


def _assign_topics(chat: Chat) -> None:
    topics = {message.id: str(message.service_details.get("title") or message.service_details.get("new_title") or f"Topic {message.id}") for message in chat.messages if message.service_action == "topic_created"}
    for message in chat.messages:
        if message.reply_to_id in topics:
            message.topic_id = message.reply_to_id
            message.topic_title = topics[message.reply_to_id]


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
