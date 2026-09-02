from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tg2notebooklm.model import Attachment, Chat, Message

TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".jsonc", ".html", ".htm", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".py", ".js", ".ts",
    ".tsx", ".jsx", ".css", ".scss", ".sh", ".bat", ".cmd", ".ps1", ".jinja", ".diff", ".patch",
}


def count_words(text: str) -> int:
    return len(text.split())



def render_chat_header(chat: Chat, part: int | None = None) -> str:
    suffix = f" — part {part:03d}" if part is not None else ""
    if chat.input_format == "file_dump":
        lines = [
            f"# File dump: {chat.name}{suffix}",
            "",
            f"- Source: local folder (recursive), {len(chat.messages):,} files",
            "- Message markers are file ordinals (`file-NNNNNN`); attachments are the original files.",
            "",
        ]
        return "\n".join(lines)
    lines = [
        f"# Telegram chat: {chat.name}{suffix}",
        "",
        f"- Chat type: `{chat.kind}`",
        f"- Chat ID: `{chat.id or 'unknown'}`",
        f"- Input format: `{chat.input_format}`",
        "- Message markers use Telegram export IDs; replies and topics point to those IDs.",
        "",
    ]
    return "\n".join(lines)


def code_fence_for(text: str) -> str:
    """Return a backtick fence longer than any backtick run inside text."""
    longest = max(map(len, re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render_message(chat: Chat, message: Message, inline_text_max_bytes: int) -> str:
    if message.kind == "date_marker":
        return f"\n## {message.text}\n"

    if chat.input_format == "file_dump":
        heading = f"### File {message.sequence:,} · {chat.name} · {message.id}"
    else:
        date_label = _date_label(message.timestamp)
        author = message.author or message.author_id or "Unknown/deleted account"
        heading = f"### {date_label} · {author} · msg {message.id}"
    lines = [heading]

    metadata: list[str] = []
    if message.kind == "service":
        metadata.append(f"service={message.service_action or 'unknown'}")
    if message.edited_at:
        metadata.append(f"edited={message.edited_at}")
    if message.reply_to_id:
        target = f"{message.reply_to_peer_id}/" if message.reply_to_peer_id else ""
        metadata.append(f"reply_to={target}{message.reply_to_id}")
    if message.topic_title:
        metadata.append(f"topic={message.topic_title} (root {message.topic_id})")
    if message.saved_from:
        metadata.append(f"saved_from={message.saved_from}")
    if message.via_bot:
        metadata.append(f"via_bot={message.via_bot}")
    if message.forwarded_from:
        forwarded = message.forwarded_from
        if message.forwarded_from_id:
            forwarded += f" [{message.forwarded_from_id}]"
        if message.forwarded_date:
            forwarded += f" · original date={message.forwarded_date}"
        metadata.append(f"forwarded_from={forwarded}")
    if metadata:
        lines.append("_" + " · ".join(metadata) + "_")

    if message.kind == "service":
        lines.append(_render_service(message))
    elif message.text.strip():
        lines.append(message.text.strip())
    elif not message.attachments and message.poll is None:
        lines.append("[empty message]")

    if message.poll:
        lines.extend(_render_poll(message))
    if message.reactions:
        lines.append("Reactions: " + ", ".join(_render_reaction(reaction) for reaction in message.reactions))
    if message.inline_buttons:
        rendered_buttons = []
        for button in message.inline_buttons:
            text = str(button.get("text") or "button")
            target = button.get("data")
            rendered_buttons.append(f"{text} → {target}" if target else text)
        lines.append("Inline buttons: " + " | ".join(rendered_buttons))
    for attachment in message.attachments:
        lines.extend(_render_attachment(chat, attachment, inline_text_max_bytes))
    if message.extra:
        lines.append("Unrecognized Telegram fields: `" + ", ".join(sorted(message.extra)) + "`")
    lines.append(f"<!-- tg:chat={chat.id or 'unknown'};message={message.id};sequence={message.sequence} -->")
    return "\n\n".join(part for part in lines if part) + "\n"


def _render_reaction(reaction: Any) -> str:
    rendered = f"{reaction.value} ×{reaction.count}"
    reactors = [str(item.get("from")) for item in reaction.recent if isinstance(item, dict) and item.get("from")]
    if reactors:
        rendered += " (recent: " + ", ".join(reactors) + ")"
    return rendered


def _render_service(message: Message) -> str:
    details = message.service_details
    action = (message.service_action or "service").replace("_", " ")
    if message.text.strip():
        return f"[Service event: {message.text.strip()}]"
    parts = [action]
    if details.get("title"):
        parts.append(f"title={details['title']}")
    if details.get("new_title"):
        parts.append(f"new title={details['new_title']}")
    if details.get("members"):
        parts.append("members=" + ", ".join(map(str, details["members"])))
    if details.get("inviter"):
        parts.append(f"inviter={details['inviter']}")
    return "[Service event: " + "; ".join(parts) + "]"


def _render_poll(message: Message) -> list[str]:
    assert message.poll is not None
    poll = message.poll
    lines = [f"#### Poll: {poll.question}"]
    for answer in poll.answers:
        suffix = []
        if answer.voters is not None:
            suffix.append(f"{answer.voters} voters")
        if answer.chosen:
            suffix.append("chosen")
        lines.append(f"- {answer.text}" + (f" ({', '.join(suffix)})" if suffix else ""))
    if poll.total_voters is not None:
        lines.append(f"Total voters: {poll.total_voters}")
    if poll.closed is not None:
        lines.append(f"Closed: {str(poll.closed).lower()}")
    return lines


def _render_attachment(chat: Chat, attachment: Attachment, inline_text_max_bytes: int) -> list[str]:
    name = attachment.name or attachment.reference or attachment.kind
    details = [f"type={attachment.kind}"]
    if attachment.mime_type:
        details.append(f"mime={attachment.mime_type}")
    if attachment.size is not None:
        details.append(f"declared_size={attachment.size}")
    if attachment.width and attachment.height:
        details.append(f"dimensions={attachment.width}x{attachment.height}")
    if attachment.duration_seconds is not None:
        details.append(f"duration={attachment.duration_seconds}s")
    if attachment.available:
        details.append("exported=yes")
    else:
        details.append(f"exported=no ({attachment.reason or 'not available'})")
    lines = [f"Attachment: `{name}` ({'; '.join(details)})"]

    path = attachment.path
    if path and attachment.available and path.suffix.casefold() in TEXT_ATTACHMENT_EXTENSIONS:
        if path.stat().st_size <= inline_text_max_bytes:
            text, encoding = _read_text_attachment(path)
            if text:
                language = _fence_language(path)
                fence = code_fence_for(text)
                lines.append(f"Attached text (`{path.name}`, decoded as {encoding}):\n\n{fence}{language}\n{text}\n{fence}")
            else:
                lines.append(f"Attached text `{path.name}` could not be decoded without binary data.")
        else:
            lines.append(f"Attached text `{path.name}` exceeds inline limit ({inline_text_max_bytes} bytes).")
    return lines


def _read_text_attachment(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return "", "binary"
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1251", "latin-1"):
        try:
            text = data.decode(encoding)
            return text.replace("\r\n", "\n").replace("\r", "\n"), encoding
        except UnicodeDecodeError:
            continue
    return "", "unknown"


def _fence_language(path: Path) -> str:
    return {
        ".py": "python", ".json": "json", ".jsonc": "json", ".html": "html", ".htm": "html",
        ".xml": "xml", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".js": "javascript",
        ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx", ".css": "css", ".sh": "bash",
        ".ps1": "powershell", ".md": "markdown", ".markdown": "markdown", ".csv": "csv",
    }.get(path.suffix.casefold(), "text")


def _date_label(timestamp: str | None) -> str:
    if not timestamp:
        return "Unknown date"
    normalized = timestamp.replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(normalized)
        return value.isoformat(sep=" ", timespec="seconds")
    except ValueError:
        return timestamp
