"""Generate a synthetic Telegram export for smoke-testing tg2notebooklm.

Creates examples/output/ChatExport_example/ with a JSON export and a one-page HTML
export covering: plain text, rich entities, replies, forwards with date, reactions,
a poll, a service event, a text attachment, an image attachment, and a placeholder.

Run:  python examples/make_example_export.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
TARGET = HERE / "output" / "ChatExport_example"


def main() -> None:
    files = TARGET / "files"
    files.mkdir(parents=True, exist_ok=True)
    image_path = files / "round_rectangle.png"
    image = Image.new("RGB", (64, 48), "#244f9e")
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 52, 36), fill="#e4b33f")
    image.save(image_path)
    note_path = files / "note.txt"
    note_path.write_text("Attachment body: example text file shipped with a message.\n", encoding="utf-8")

    result = {
        "name": "Example chat",
        "type": "private_group",
        "id": 100200300,
        "messages": [
            {
                "id": 1,
                "type": "service",
                "date": "2026-08-01T09:00:00",
                "date_unixtime": "1785574800",
                "actor": "Alice",
                "actor_id": "user111",
                "action": "create_group",
                "title": "Example chat",
                "text": "",
                "text_entities": [],
            },
            {
                "id": 10,
                "type": "message",
                "date": "2026-08-01T09:05:00",
                "date_unixtime": "1785575100",
                "from": "Alice",
                "from_id": "user111",
                "text": ["Launch checklist: ", {"type": "bold", "text": "ready"}, " — see ", {"type": "text_link", "text": "docs", "href": "https://example.test/docs"}],
                "text_entities": [
                    {"type": "plain", "text": "Launch checklist: "},
                    {"type": "bold", "text": "ready"},
                    {"type": "plain", "text": " — see "},
                    {"type": "text_link", "text": "docs", "href": "https://example.test/docs"},
                ],
                "photo": "files/round_rectangle.png",
                "photo_file_size": image_path.stat().st_size,
                "width": 64,
                "height": 48,
            },
            {
                "id": 11,
                "type": "message",
                "date": "2026-08-01T09:06:00",
                "date_unixtime": "1785575160",
                "from": "Bob",
                "from_id": "user222",
                "reply_to_message_id": 10,
                "text": "Replying to the checklist",
                "text_entities": [{"type": "plain", "text": "Replying to the checklist"}],
                "reactions": [{"type": "emoji", "count": 2, "emoji": "👍"}],
            },
            {
                "id": 12,
                "type": "message",
                "date": "2026-08-01T09:07:00",
                "date_unixtime": "1785575220",
                "from": "Alice",
                "from_id": "user111",
                "forwarded_from": "Source channel",
                "text": "Forwarded announcement",
                "text_entities": [{"type": "plain", "text": "Forwarded announcement"}],
                "file": "files/note.txt",
                "file_name": "note.txt",
                "file_size": note_path.stat().st_size,
                "mime_type": "text/plain",
            },
            {
                "id": 13,
                "type": "message",
                "date": "2026-08-01T09:08:00",
                "date_unixtime": "1785575280",
                "from": "Bob",
                "from_id": "user222",
                "text": "",
                "text_entities": [],
                "photo": "(File not included. Change data exporting settings to download.)",
                "photo_file_size": 54021,
                "width": 960,
                "height": 720,
                "poll": {
                    "question": "Ship on Friday?",
                    "closed": False,
                    "total_voters": 7,
                    "answers": [
                        {"text": "Yes", "voters": 5, "chosen": True},
                        {"text": "No", "voters": 2, "chosen": False},
                    ],
                },
            },
        ],
    }
    (TARGET / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET / 'result.json'}")


if __name__ == "__main__":
    main()
