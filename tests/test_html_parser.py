from pathlib import Path

from tg2notebooklm.parsers.html_export import parse_html_export


PAGE_ONE = """<!doctype html><html><body>
<div class="page_header"><div class="text bold">Research chat</div></div>
<div class="history">
  <div class="message service" id="message-1"><div class="body details">1 August 2026</div></div>
  <div class="message default clearfix" id="message10">
    <div class="body">
      <div class="pull_right date details" title="01.08.2026 10:00:00 UTC+00:00">10:00</div>
      <div class="from_name">Alice</div>
      <div class="text">Hello <strong>world</strong><br><a href="https://example.test">link</a></div>
    </div>
  </div>
  <div class="message default clearfix joined" id="message11">
    <div class="body">
      <div class="pull_right date details" title="01.08.2026 10:01:00 UTC+00:00">10:01</div>
      <div class="reply_to details">In reply to <a href="#go_to_message10">this message</a></div>
      <div class="text">Reply</div>
      <span class="reactions"><span class="reaction"><span class="emoji">👍</span><span class="count">3</span></span></span>
    </div>
  </div>
</div>
<a class="pagination block_link" href="messages2.html">Next messages</a>
</body></html>"""

PAGE_TWO = """<!doctype html><html><body><div class="history">
  <div class="message default clearfix" id="message12">
    <div class="body">
      <div class="pull_right date details" title="01.08.2026 10:02:00 UTC+00:00">10:02</div>
      <div class="from_name">Bob</div>
      <div class="pull_left forwarded userpic_wrap"></div>
      <div class="forwarded body">
        <div class="from_name">Source channel <span class="date details">01.08.2026 09:00:00</span></div>
        <div class="text">Forwarded text</div>
        <div class="media_wrap clearfix"><a class="media media_file" href="files/note.txt"><div class="title bold">note.txt</div></a></div>
      </div>
    </div>
  </div>
  <div class="message default clearfix joined" id="message13">
    <div class="body">
      <div class="pull_right date details" title="01.08.2026 10:03:00 UTC+00:00">10:03</div>
      <div class="media_wrap clearfix"><div class="media media_photo"><div class="title bold">Photo</div><div class="status details">Not included</div></div></div>
    </div>
  </div>
</div></body></html>"""


def test_parse_paginated_html_preserves_joined_author_forward_and_media(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "note.txt").write_text("attachment body", encoding="utf-8")
    (tmp_path / "messages.html").write_text(PAGE_ONE, encoding="utf-8")
    (tmp_path / "messages2.html").write_text(PAGE_TWO, encoding="utf-8")

    chat = parse_html_export(tmp_path)

    assert chat.name == "Research chat"
    assert [message.id for message in chat.messages if message.kind == "message"] == ["10", "11", "12", "13"]
    first, reply, forwarded, missing = [message for message in chat.messages if message.kind == "message"]
    assert first.text == "Hello **world**\n[link](https://example.test)"
    assert reply.author == "Alice"
    assert reply.reply_to_id == "10"
    assert reply.reactions[0].count == 3
    assert forwarded.forwarded_from == "Source channel"
    assert forwarded.forwarded_date == "01.08.2026 09:00:00"
    assert forwarded.text == "Forwarded text"
    assert forwarded.attachments[0].available is True
    assert missing.author == "Bob"
    assert missing.attachments[0].available is False
