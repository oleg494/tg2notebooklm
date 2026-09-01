import json
from pathlib import Path

from tg2notebooklm.cli import main


def test_cli_inspect_and_convert_json(tmp_path: Path, capsys) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "result.json").write_text(
        json.dumps(
            {
                "name": "Tiny chat",
                "type": "personal_chat",
                "id": 1,
                "messages": [
                    {
                        "id": 1,
                        "type": "message",
                        "date": "2026-08-01T10:00:00",
                        "date_unixtime": "1785578400",
                        "from": "Alice",
                        "from_id": "user1",
                        "text": "hello",
                        "text_entities": [{"type": "plain", "text": "hello"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["inspect", str(export_dir)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["format"] == "json"
    assert inspected["messages"] == 1

    output = tmp_path / "out"
    assert main(["convert", str(export_dir), "--output", str(output), "--source-limit", "5"]) == 0
    converted = json.loads(capsys.readouterr().out)
    assert converted["source_count"] >= 2
    assert (output / "sources" / "00_index.md").exists()
