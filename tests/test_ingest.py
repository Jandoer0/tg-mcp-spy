"""Тесты парсеров Telegram и RSS (без сети)."""
from tg_spy.ingest import rss, telegram

TG_HTML = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="durov/123">
    <div class="tgme_widget_message_text">Привет <a href="#">мир</a> #тест</div>
    <time datetime="2026-01-01T10:00:00+00:00"></time>
    <a class="tgme_widget_message_date" href="https://t.me/durov/123">date</a>
  </div>
</div>
"""

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Заголовок</title>
    <link>https://example.com/1</link>
    <guid>guid-1</guid>
    <pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate>
    <description>&lt;p&gt;Текст &lt;b&gt;жирный&lt;/b&gt; поста&lt;/p&gt;</description>
  </item>
</channel></rss>
"""


def test_telegram_parse():
    posts = telegram.parse_posts(TG_HTML)
    assert len(posts) == 1
    p = posts[0]
    assert p["ext_id"] == 123
    assert "Привет" in p["text"]
    assert p["date"] == "2026-01-01"


def test_rss_url():
    assert rss.rsshub_telegram_url("https://rsshub.app", "durov") == (
        "https://rsshub.app/telegram/channel/durov"
    )


def test_rss_parse():
    posts = rss.parse_feed(RSS_XML)
    assert len(posts) == 1
    p = posts[0]
    assert p["ext_id"] == "guid-1"
    assert "жирный" in p["text"]  # HTML очищен от тегов
    assert "<p>" not in p["text"]
    assert p["date"] == "2026-01-01"
