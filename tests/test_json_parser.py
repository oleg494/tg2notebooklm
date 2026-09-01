import json
from pathlib import Path

from tg2notebooklm.parsers.json_export import parse_json_export


def test_parse_json_preserves_relations_entities_and_missing_media(tmp_path: Path) -> None:
    export = {
        "name": "Research chat",
        "type": "private_group",
        "id": 42,
        "messages": [
            {
                "id": 10,
                "type": "message",
                "date": "2026-08-01T10:00:00",
                "date_unixtime": "1785578400",
                "from": "Alice",
                "from_id": "user1",
                "text": ["Read ", {"type": "text_link", "text": "this", "href": "https://example.test"}],
                "text_entities": [
                    {"type": "plain", "text": "Read "},
                    {"type": "text_link", "text": "this", "href": "https://example.test"},
                ],
                "reactions": [{"type": "emoji", "count": 2, "emoji": "👍"}],
            },
            {
                "id": 11,
                "type": "message",
                "date": "2026-08-01T10:01:00",
                "date_unixtime": "1785578460",
                "from": "Bob",
                "from_id": "user2",
                "reply_to_message_id": 10,
                "forwarded_from": "Source channel",
                "edited": "2026-08-01T10:02:00",
                "file": "(File not included. Change data exporting settings to download.)",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "text": "Reply",
                "text_entities": [{"type": "plain", "text": "Reply"}],
                "unknown_future_field": {"kept": True},
            },
            {
                "id": 12,
                "type": "service",
                "date": "2026-08-01T10:03:00",
                "date_unixtime": "1785578580",
                "actor": "Alice",
                "actor_id": "user1",
                "action": "invite_members",
                "members": ["Bob"],
                "text": "",
                "text_entities": [],
            },
        ],
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    chats = parse_json_export(path)

    assert len(chats) == 1
    chat = chats[0]
    assert chat.name == "Research chat"
    assert len(chat.messages) == 3
    assert chat.messages[0].text == "Read [this](https://example.test)"
    assert chat.messages[0].reactions[0].count == 2
    assert chat.messages[1].reply_to_id == "10"
    assert chat.messages[1].forwarded_from == "Source channel"
    assert chat.messages[1].attachments[0].available is False
    assert "not included" in chat.messages[1].attachments[0].reason.lower()
    assert chat.messages[1].extra["unknown_future_field"] == {"kept": True}
    assert chat.messages[2].kind == "service"
    assert chat.messages[2].service_action == "invite_members"


def test_parse_full_account_json_returns_each_chat(tmp_path: Path) -> None:
    export = {
        "chats": {
            "list": [
                {"name": "One", "type": "personal_chat", "id": 1, "messages": []},
                {"name": "Two", "type": "private_group", "id": 2, "messages": []},
            ]
        }
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    assert [chat.name for chat in parse_json_export(path)] == ["One", "Two"]
