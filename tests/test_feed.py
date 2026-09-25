"""Тесты новостной ленты: очистка HTML, подписи времени, парсинг RSS, кэш."""

import json
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

from app import feed
from app.timeutils import now
from tests.conftest import make_settings


def test_strip_html():
    assert feed._strip_html("<p>Привет <b>мир</b></p>") == "Привет мир"
    assert feed._strip_html("   много   пробелов ") == "много пробелов"
    assert feed._strip_html(None) == ""


def _rss_xml() -> bytes:
    return """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Политика &lt;b&gt;новость&lt;/b&gt;</title>
        <link>https://tass.ru/politika/1</link>
        <guid>https://tass.ru/politika/1</guid>
        <pubDate>Fri, 25 Sep 2026 08:00:00 GMT</pubDate>
        <category>Политика</category>
        <description>Событие в политике</description>
      </item>
      <item>
        <title>Спорт</title>
        <link>https://tass.ru/sport/1</link>
        <guid>https://tass.ru/sport/1</guid>
        <pubDate>Fri, 25 Sep 2026 07:00:00 GMT</pubDate>
        <category>Спорт</category>
        <description>Не наша рубрика</description>
      </item>
      <item>
        <title>&lt;i&gt;Общество EOF описание слишком длинное повторяющееся описание много текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста текста</title>
        <link>https://tass.ru/society/1</link>
        <guid>https://tass.ru/society/1</guid>
        <pubDate>Fri, 25 Sep 2026 06:00:00 GMT</pubDate>
        <category>Общество</category>
        <description>Очень длинное описание новости для проверки обрезки описания и корректности алгоритма работы с длинными текстами</description>
      </item>
    </channel></rss>
    """.encode()


class _StubResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_fetch_tass_filters_categories_and_sorts(monkeypatch):
    monkeypatch.setattr(feed, "settings", make_settings())
    monkeypatch.setattr(feed, "requests", SimpleNamespace(get=lambda *a, **k: _StubResp(_rss_xml())))
    items = feed._fetch_tass()
    assert items is not None
    titles = [i["title"] for i in items]
    assert "Политика новость" in titles
    assert "Спорт" not in titles
    assert any(t.startswith("Общество EOF") for t in titles)
    assert all(len(i["description"]) <= feed._DESCRIPTION_LIMIT + 1 for i in items)

    dates = [datetime.fromisoformat(i["published_at"]) for i in items]
    assert dates == sorted(dates, reverse=True)


def test_published_labels():
    ref = datetime(2026, 9, 25, 12, 0)
    assert feed._published_label(ref, ref) == "сегодня в 12:00"
    assert feed._published_label(ref - timedelta(days=1), ref) == "вчера в 12:00"
    old = datetime(2026, 9, 1, 10, 0)
    assert feed._published_label(old, ref) == "01.09.2026 10:00"


def _write_cache(path, cached_at, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"cached_at": cached_at.isoformat(), "schema": feed._CACHE_SCHEMA, "data": data},
        ensure_ascii=False,
    ))


def test_fresh_news_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "_CACHE_PATH", tmp_path / "cache.json")
    fresh = [{"title": "новость", "category": "политика", "published_at": "2026-09-25T08:00:00+00:00"}]
    _write_cache(tmp_path / "cache.json", now(), fresh)

    def forbidden():
        raise AssertionError("сеть не должна вызываться при свежем кэше")

    monkeypatch.setattr(feed, "_fetch_tass", forbidden)
    assert feed._cached_news() == fresh


def test_stale_news_refetches(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(feed, "settings", make_settings(news_fetch_minutes=15))
    _write_cache(tmp_path / "cache.json", now() - timedelta(hours=1), [{"title": "old"}])

    fresh = [{"title": "новое", "category": "общество", "published_at": "2026-09-25T09:00:00+00:00"}]
    monkeypatch.setattr(feed, "_fetch_tass", lambda: fresh)
    assert feed._cached_news() == fresh


def test_feed_error_returns_stale_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "_CACHE_PATH", tmp_path / "cache.json")
    stale = [{"title": "старое", "category": "политика", "published_at": "2026-09-24T08:00:00+00:00"}]
    _write_cache(tmp_path / "cache.json", now() - timedelta(hours=2), stale)
    monkeypatch.setattr(feed, "_fetch_tass", lambda: None)
    assert feed._cached_news() == stale


def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(feed, "settings", make_settings(news_enabled=False))

    def forbidden():
        raise AssertionError("не должен читать ленту при отключённых новостях")

    monkeypatch.setattr(feed, "_cached_news", forbidden)
    assert feed.get_news_items() == []