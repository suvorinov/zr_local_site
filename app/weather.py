"""Сервис для получения прогноза погоды.

Цепочка источников (первый доступный):
    1. Open-Meteo API (бесплатно, без API-ключа);
    2. OpenWeatherMap (нужен ключ в настройках);
    3. wttr.in (аварийный, без ключа).

Ответы нормализуются в общий список почасовых прогнозов и кэшируются
в файл (data/weather_cache.json), чтобы не дёргать API на каждый запрос.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import niquests as requests
from openmeteo_requests import Client as OpenMeteoClient

from app.config import settings
from app.timeutils import now

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data") / "weather_cache.json"
_CACHE_SCHEMA = 4

# Цветные эмодзи (U+FE0F) вместо монохромных символов — выглядят менее мрачно
_WMO_CODES = {
    0: "☀\ufe0f", 1: "🌤\ufe0f", 2: "⛅\ufe0f", 3: "☁\ufe0f",
    45: "🌫\ufe0f", 48: "🌫\ufe0f",
    51: "🌦\ufe0f", 53: "🌦\ufe0f", 55: "🌦\ufe0f",
    56: "🌦\ufe0f", 57: "🌦\ufe0f",
    61: "🌧\ufe0f", 63: "🌧\ufe0f", 65: "🌧\ufe0f",
    66: "🌧\ufe0f", 67: "🌧\ufe0f",
    71: "🌨\ufe0f", 73: "🌨\ufe0f", 75: "🌨\ufe0f", 77: "🌨\ufe0f",
    80: "🌧\ufe0f", 81: "🌧\ufe0f", 82: "🌧\ufe0f",
    85: "🌨\ufe0f", 86: "🌨\ufe0f",
    95: "⛈\ufe0f", 96: "⛈\ufe0f", 99: "⛈\ufe0f",
}

_THUNDER = {95, 96, 99}
_DRIZZLE = {51, 53, 55, 56, 57}
_RAIN = {61, 63, 65, 66, 67, 80, 81, 82}
_SNOW = {71, 73, 75, 77, 85, 86}

_OWM_TO_WMO = {
    200: 95, 201: 95, 202: 95, 210: 95, 211: 95, 212: 95, 221: 95,
    230: 95, 231: 95, 232: 95,
    300: 51, 301: 51, 302: 51, 310: 51, 311: 51, 312: 51, 313: 51,
    314: 51, 321: 51,
    500: 61, 501: 61, 502: 61, 503: 61, 504: 61, 511: 61, 520: 80,
    521: 80, 522: 80, 531: 80,
    600: 71, 601: 71, 602: 71, 611: 71, 612: 71, 613: 71, 615: 71,
    616: 71, 620: 71, 621: 71, 622: 71,
    701: 45, 711: 45, 721: 45, 741: 45, 761: 45, 762: 45, 771: 45, 781: 45,
    800: 0,
    801: 1, 802: 1, 803: 2, 804: 3,
}

_WTTR_TO_WMO = {
    113: 0, 116: 1, 119: 3, 122: 3,
    143: 45, 248: 45, 260: 45,
    176: 51, 263: 51, 266: 51, 281: 51, 284: 51, 293: 61, 296: 61,
    299: 61, 302: 61, 305: 61, 308: 61, 311: 61, 314: 61, 317: 51, 320: 51,
    179: 61, 182: 61, 185: 61, 353: 61, 356: 61, 359: 61, 362: 61,
    365: 61, 368: 61, 371: 61, 374: 61, 377: 61,
    200: 95, 386: 95, 389: 95, 392: 95, 395: 95,
    227: 71, 230: 71, 323: 71, 326: 71, 329: 71, 332: 71, 335: 71,
    338: 71, 350: 71,
    400: 71, 401: 71, 402: 71, 403: 71, 404: 71, 405: 71, 406: 71,
    407: 71, 420: 71, 421: 71, 422: 71, 425: 71,
}

_TIMEOUT = 12


class _TimeoutSession(requests.Session):
    """Сессия, у которой каждый запрос ограничен по времени."""

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", _TIMEOUT)
        return super().get(url, **kwargs)


_session = _TimeoutSession()
_om_client = OpenMeteoClient(session=_session)


def _wmo_emoji(owm_or_wmo: int) -> str:
    """Преобразует код погоды в цветной эмодзи."""
    return _WMO_CODES.get(owm_or_wmo, "?")


def _to_mmhg(hpa) -> int | None:
    """Переводит давление в гектопаскалях в мм рт. ст. (целое число)."""
    try:
        return int(round(float(hpa) * 0.750062))
    except (TypeError, ValueError):
        return None


def _fetch_openmeteo() -> list[dict] | None:
    """Просит почасовой прогноз у Open-Meteo."""
    params = {
        "latitude": settings.weather_lat,
        "longitude": settings.weather_lon,
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
            "surface_pressure",
        ],
        "timezone": settings.timezone,
        "forecast_hours": 24,
    }
    try:
        responses = _om_client.weather_api(
            "https://api.open-meteo.com/v1/forecast", params=params
        )
        response = responses[0]
        hourly = response.Hourly()
        if not hourly or hourly.Variables() is None:
            return None
    except Exception as e:
        logger.warning("Open-Meteo недоступен: %s", e)
        return None

    tz = ZoneInfo(settings.timezone)
    temps = hourly.Variables(0).ValuesAsNumpy()
    precips = hourly.Variables(1).ValuesAsNumpy()
    codes = hourly.Variables(2).ValuesAsNumpy()
    pressures = hourly.Variables(3).ValuesAsNumpy()
    result = []
    for i, t in enumerate(hourly.Time()):
        result.append({
            "hour": datetime.fromtimestamp(t, tz=tz).strftime("%H:%M"),
            "temp": round(float(temps[i])),
            "precip": int(round(float(precips[i]))) if precips is not None else 0,
            "pressure_mm": _to_mmhg(float(pressures[i])) if pressures is not None else None,
            "emoji": _wmo_emoji(int(codes[i])),
        })
    return result


def _fetch_openweathermap() -> list[dict] | None:
    """Просит прогноз у OpenWeatherMap (каждые 3 часа, 24 часа)."""
    key = settings.weather_openweathermap_key.strip()
    if not key:
        return None
    params = {
        "lat": settings.weather_lat,
        "lon": settings.weather_lon,
        "appid": key,
        "units": "metric",
        "lang": "ru",
        "cnt": 8,
    }
    try:
        resp = _session.get(
            "https://api.openweathermap.org/data/2.5/forecast", params=params
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("OpenWeatherMap недоступен: %s", e)
        return None

    tz = ZoneInfo(settings.timezone)
    result = []
    for item in data.get("list", []):
        weather_id = (item.get("weather") or [{}])[0].get("id")
        result.append({
            "hour": datetime.fromtimestamp(item["dt"], tz=tz).strftime("%H:%M"),
            "temp": round(float(item["main"]["temp"])),
            "precip": round(float(item.get("pop", 0) or 0) * 100),
            "pressure_mm": _to_mmhg((item.get("main") or {}).get("pressure")),
            "emoji": _wmo_emoji(_OWM_TO_WMO.get(weather_id, 45 if weather_id else 0)),
        })
    return result or None


def _fetch_wttrin() -> list[dict] | None:
    """Просит прогноз у wttr.in (аварийный источник)."""
    location = quote(settings.weather_wttr_city.strip() or "Ryazan")
    try:
        resp = _session.get(f"https://wttr.in/{location}?format=j1&lang=ru")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("wttr.in недоступен: %s", e)
        return None

    tz = ZoneInfo(settings.timezone)
    result = []
    seen: set[str] = set()
    for day in data.get("weather", []):
        for hour in day.get("hourly", []):
            raw_time = str(hour.get("time", "0")).zfill(4)
            if len(raw_time) != 4:
                continue
            key = f"{day.get('date')} {raw_time[:2]}:{raw_time[2:]}"
            if key in seen:
                continue
            seen.add(key)
            chance = max(
                int(hour.get("chanceofrain", 0) or 0),
                int(hour.get("chanceofsnow", 0) or 0),
            )
            result.append({
                "hour": f"{raw_time[:2]}:{raw_time[2:]}",
                "temp": round(float(hour.get("tempC", 0) or 0)),
                "precip": chance,
                "pressure_mm": _to_mmhg(hour.get("pressure")),
                "emoji": _wmo_emoji(_WTTR_TO_WMO.get(int(hour.get("weatherCode", 0) or 0), 0)),
            })
    return result or None


def _fetch_forecast() -> tuple[str, list[dict]] | None:
    """Получает прогноз по цепочке источников.

    Returns:
        Кортеж (имя источника, список почасовых прогнозов)
        или None, если ни один источник не ответил.
    """
    for name, fetcher in (
        ("open-meteo", _fetch_openmeteo),
        ("openweathermap", _fetch_openweathermap),
        ("wttr.in", _fetch_wttrin),
    ):
        data = fetcher()
        if data:
            logger.info("Прогноз погоды получен от %s (%d часов)", name, len(data))
            return name, data
    return None


def _cached_forecast() -> list[dict]:
    """Возвращает прогноз из кэша или загружает новый.

    Кэш считается свежим в течение settings.weather_refresh_minutes.
    При недоступности всех источников возвращается устаревший кэш.

    Returns:
        Список почасовых прогнозов (может быть пустым).
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
            if (ref_time - cache_time).total_seconds() < settings.weather_refresh_minutes * 60:
                return cached["data"]
        except (ValueError, KeyError, TypeError):
            pass

    fetched = _fetch_forecast()
    if fetched is None:
        if _CACHE_PATH.exists():
            try:
                raw = json.loads(_CACHE_PATH.read_text())
                if raw.get("schema") == _CACHE_SCHEMA:
                    logger.warning("Все источники погоды недоступны, использую кэш")
                    return raw["data"]
            except (ValueError, KeyError, TypeError):
                pass
        return []

    provider, data = fetched
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(
        {
            "cached_at": ref_time.isoformat(),
            "schema": _CACHE_SCHEMA,
            "provider": provider,
            "data": data,
        },
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
    """Возвращает почасовой прогноз погоды на 6 ближайших часов.

    Returns:
        Список прогнозов по часам с полями:
        hour, temp, precip, pressure_mm, emoji.
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