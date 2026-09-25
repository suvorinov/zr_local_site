"""Тесты погоды: пересчёт единиц, источники (мок сети), кэш."""

import json
from datetime import timedelta

from app import weather
from app.timeutils import now
from tests.conftest import make_settings


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _StubSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, **kwargs):
        return _StubResponse(self._payload)


def _write_cache(path, cached_at, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"cached_at": cached_at.isoformat(), "schema": weather._CACHE_SCHEMA, "data": data},
        ensure_ascii=False,
    ))


def test_mmhg_conversion():
    assert weather._to_mmhg(1013.25) == 760
    assert weather._to_mmhg(None) is None
    assert weather._to_mmhg("не число") is None


def test_wmo_emoji():
    assert "☀" in weather._wmo_emoji(0)
    assert weather._wmo_emoji(99999) == "?"


def test_openweathermap_skipped_without_key(monkeypatch):
    monkeypatch.setattr(weather, "settings", make_settings(weather_openweathermap_key="   "))
    assert weather._fetch_openweathermap() is None


def test_openweathermap_parsing(monkeypatch):
    monkeypatch.setattr(weather, "settings", make_settings(weather_openweathermap_key="key"))
    payload = {"list": [{
        "dt": 1700000000, "main": {"temp": 22.5, "pressure": 1013},
        "pop": 0.3, "weather": [{"id": 800}],
    }]}
    monkeypatch.setattr(weather, "_session", _StubSession(payload))
    result = weather._fetch_openweathermap()
    assert result is not None
    assert result[0]["temp"] == 22
    assert result[0]["precip"] == 30
    assert result[0]["pressure_mm"] == 760


def test_wttrin_parsing(monkeypatch):
    monkeypatch.setattr(weather, "settings", make_settings(weather_wttr_city="Ryazan"))
    payload = {"weather": [{
        "date": "2026-09-25", "hourly": [
            {"time": "900", "tempC": 15, "chanceofrain": 40, "chanceofsnow": 10,
             "pressure": 1000, "weatherCode": 113},
        ],
    }]}
    monkeypatch.setattr(weather, "_session", _StubSession(payload))
    result = weather._fetch_wttrin()
    assert result is not None
    hour = result[0]
    assert hour["hour"] == "09:00"
    assert hour["temp"] == 15
    assert hour["precip"] == 40


def test_fresh_cache_used_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "_CACHE_PATH", tmp_path / "cache.json")
    fresh = [{"hour": "09:00", "temp": 20, "precip": 0, "pressure_mm": 750, "emoji": "☀️"}]
    _write_cache(tmp_path / "cache.json", now(), fresh)

    def forbidden():
        raise AssertionError("сеть не должна вызываться при свежем кэше")

    monkeypatch.setattr(weather, "_fetch_forecast", forbidden)
    assert weather.get_all_forecast() == fresh


def test_stale_cache_refetches(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "_CACHE_PATH", tmp_path / "cache.json")
    _write_cache(tmp_path / "cache.json", now() - timedelta(hours=2), [{"hour": "old"}])
    monkeypatch.setattr(weather, "settings", make_settings(weather_refresh_minutes=60))

    fresh = [{"hour": "10:00", "temp": 18, "precip": 0, "pressure_mm": 750, "emoji": "☁️"}]
    monkeypatch.setattr(weather, "_fetch_forecast", lambda: ("open-meteo", fresh))
    assert weather.get_all_forecast() == fresh


def test_all_sources_down_uses_stale_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "_CACHE_PATH", tmp_path / "cache.json")
    stale = [{"hour": "old", "temp": 1, "precip": 0, "pressure_mm": 700, "emoji": "?"}]
    _write_cache(tmp_path / "cache.json", now() - timedelta(hours=5), stale)
    monkeypatch.setattr(weather, "_fetch_forecast", lambda: None)
    assert weather.get_all_forecast() == stale


def test_no_cache_and_no_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(weather, "_fetch_forecast", lambda: None)
    assert weather.get_all_forecast() == []


def test_get_forecast_returns_up_to_six(monkeypatch):
    hours = [{"hour": f"{h:02d}:00", "temp": 10 + h, "precip": 0,
              "pressure_mm": 750, "emoji": "☀️"} for h in range(24)]
    monkeypatch.setattr(weather, "_cached_forecast", lambda: hours)
    six = weather.get_forecast()
    assert 1 <= len(six) <= 6