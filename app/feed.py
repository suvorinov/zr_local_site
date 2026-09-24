"""Сервис новостной ленты.

Забирает заголовки из RSS ТАСС (https://tass.ru/rss/v2.xml),
фильтрует по заданным рубрикам и возвращает актуальные новости
для инфо-блока панели.

Ответ кэшируется в файл (data/news_cache.json), чтобы не
дёргать ленту на каждый запрос.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import niquests as requests

from app.config import settings
from app.timeutils import now

logger = logging.getLogger(__name__)

_FEED_URL = "https://tass.ru/rss/v2.xml"
_CACHE_PATH = Path("data") / "news_cache.json"
_CACHE_SCHEMA = 1
_TIMEOUT = 12

_NEWS_CATEGORIES = {
    "политика", "внешняя политика", "внутренняя политика",
    "общество", "в мире",
}

_TAG_RE = re.compile(r"<[^>]+>")
_DESCRIPTION_LIMIT = 220


def _strip_html(text: str) -> str:
    """Убирает HTML-теги и лишние пробелы из текста."""
    text = _TAG_RE.sub("", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _published_label(dt: datetime, ref: datetime) -> str:
    """Форматирует время публикации: сегодня/вчера или дата."""
    today = ref.date()
    if dt.date() == today:
        return f"сегодня в {dt.strftime('%H:%M')}"
    if dt.date() == today - timedelta(days=1):
        return f"вчера в {dt.strftime('%H:%M')}"
    return dt.strftime("%d.%m.%Y %H:%M")


def _fetch_tass() -> list[dict] | None:
    """Забирает и фильтрует ленту ТАСС.

    Returns:
        Список новостей (title, category, published_label, published_at,
        description) или None при ошибке.
    """
    try:
        resp = requests.get(_FEED_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger.warning("Ошибка получения RSS ТАСС: %s", e)
        return None

    tz = ZoneInfo(settings.timezone)
    ref = now()
    items: list[dict] = []
    seen: set[str] = set()

    for item in root.iter("item"):
        categories = {
            (c.text or "").strip().lower()
            for c in item.iter("category")
        }
        if not categories & _NEWS_CATEGORIES:
            continue

        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        if not guid or guid in seen:
            continue
        seen.add(guid)

        published_raw = (item.findtext("pubDate") or "").strip()
        published_at = None
        try:
            published_at = parsedate_to_datetime(published_raw).astimezone(tz)
        except (TypeError, ValueError):
            pass
        if not published_at:
            continue

        description = _strip_html(item.findtext("description"))
        if len(description) > _DESCRIPTION_LIMIT:
            description = description[:_DESCRIPTION_LIMIT].rstrip() + "…"

        items.append({
            "title": _strip_html(item.findtext("title")).strip(),
            "category": " · ".join(sorted(categories & _NEWS_CATEGORIES)),
            "published_at": published_at.isoformat(),
            "published_label": _published_label(published_at, ref),
            "description": description,
            "link": (item.findtext("link") or guid).strip(),
        })

    items.sort(key=lambda n: n["published_at"], reverse=True)
    logger.info("Новостей ТАСС получено: %d", len(items))
    return items


def _cached_news() -> list[dict]:
    """Возвращает новости из кэша или из ленты.

    Returns:
        Список словарей новостей (может быть пустым).
    """
    ref_time = now()
    tz = ZoneInfo(settings.timezone)
    if _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            if cached.get("schema") != _CACHE_SCHEMA:
                raise KeyError("старая схема кэша")
            cache_time = datetime.fromisoformat(cached["cached_at"])
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=tz)
            if (ref_time - cache_time).total_seconds() < settings.news_fetch_minutes * 60:
                return cached["data"]
        except (ValueError, KeyError, TypeError):
            pass

    data = _fetch_tass()
    if data is None:
        if _CACHE_PATH.exists():
            try:
                raw = json.loads(_CACHE_PATH.read_text())
                if raw.get("schema") == _CACHE_SCHEMA:
                    return raw["data"]
            except (ValueError, KeyError, TypeError):
                pass
        return []

    data = data[: settings.news_max_items]
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(
        {"cached_at": ref_time.isoformat(), "schema": _CACHE_SCHEMA, "data": data},
        ensure_ascii=False,
    ))
    return data


def get_news_items() -> list[dict]:
    """Возвращает актуальные новости для инфо-блока панели.

    Returns:
        Список новостей; пустой список, если новости отключены
        или лента недоступна.
    """
    if not settings.news_enabled:
        return []
    return _cached_news()