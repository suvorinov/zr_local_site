"""Сервис для получения прогноза погоды.

Использует Open-Meteo API (бесплатно, без API-ключа).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from app.config import settings
from app.timeutils import now

logger = logging.getLogger(__name__)
_CACHE_PATH = Path("data") / "weather_cache.json"
_WMO_CODES = {
    0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️",
    45: "🌫", 48: "🌫",
    51: "🌦", 53: "🌦", 55: "🌦",
    56: "🌧", 57: "🌧",
    61: "🌧", 63: "🌧", 65: "🌧",
    66: "🌧", 67: "🌧",
    71: "🌨", 73: "🌨", 75: "🌨", 77: "🌨",
    80: "🌦", 81: "🌦", 82: "🌦",
    85: "🌨", 86: "🌨",
    95: "⛈", 96: "⛈", 99: "⛈",
}


def _wmo_emoji(code: int) -> str:
    """Преобразует WMO код погоды в эмодзи.

    Args:
        code: WMO weather code.

    Returns:
        Эмодзи для отображения.
    """
    return _WMO_CODES.get(code, "❓")


def _fetch_forecast() -> list[dict] | None:
    """Получает почасовой прогноз с Open-Meteo.

    Returns:
        Список часовых прогнозов или None при ошибке.
    """
    params = (
        f"latitude={settings.weather_lat}"
        f"&longitude={settings.weather_lon}"
        "&hourly=temperature_2m,precipitation_probability,weather_code"
        f"&timezone={quote(settings.timezone)}"
        "&forecast_hours=24"
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"

    try:
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("Ошибка получения погоды: %s", e)
        return None

    hourly = data.get("hourly", {})
    if not hourly:
        logger.warning("API погоды вернуло пустой ответ")
        return None

    logger.info("Прогноз погоды получен (%d часов)", len(hourly.get("time", [])))
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precips = hourly.get("precipitation_probability", [])
    codes = hourly.get("weather_code", [])

    result = []
    tz = ZoneInfo(settings.timezone)
    ref_time = now()
    for t, temp, precip, code in zip(times, temps, precips, codes):
        dt = datetime.fromisoformat(t).replace(tzinfo=tz)
        if dt < ref_time:
            continue
        result.append({
            "hour": dt.strftime("%H:%M"),
            "temp": round(temp),
            "precip": precip,
            "emoji": _wmo_emoji(code),
        })
    return result


def _cached_forecast() -> list[dict]:
    """Возвращает прогноз из кэша или загружает новый.

    Кэш обновляется не чаще чем раз в 15 минут.

    Returns:
        Список часовых прогнозов.
    """
    ref_time = now()
    tz = ZoneInfo(settings.timezone)
    if _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            cache_time = datetime.fromisoformat(cached["cached_at"])
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=tz)
            if (ref_time - cache_time).total_seconds() < 900:
                return cached["data"]
        except (ValueError, KeyError, TypeError):
            pass

    data = _fetch_forecast()
    if data is None:
        if _CACHE_PATH.exists():
            try:
                return json.loads(_CACHE_PATH.read_text())["data"]
            except (ValueError, KeyError):
                pass
        return []

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(
        {"cached_at": ref_time.isoformat(), "data": data},
        ensure_ascii=False,
    ))
    return data


def get_all_forecast() -> list[dict]:
    """Возвращает полный почасовой прогноз (из кэша).

    Returns:
        Список прогнозов по часам.
    """
    return _cached_forecast()


def get_forecast() -> list[dict]:
    """Возвращает почасовой прогноз погоды на сегодня (6 часов от текущего).

    Returns:
        Список прогнозов по часам с полями:
        hour, temp, precip, emoji.
    """
    all_hours = get_all_forecast()
    ref = now()
    now_hhmm = ref.hour * 100 + ref.minute
    result = []
    day_offset = 0
    prev_hour = -1
    for h in all_hours:
        parts = h["hour"].split(":")
        hh, mm = int(parts[0]), int(parts[1])
        if prev_hour >= 0 and hh < prev_hour:
            day_offset += 24
        prev_hour = hh
        hhmm = (hh + day_offset) * 100 + mm
        if hhmm < now_hhmm:
            continue
        result.append(h)
        if len(result) >= 6:
            break
    return result
