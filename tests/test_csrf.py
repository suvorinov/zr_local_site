"""Тесты CSRF-защиты: генерация, проверка подписи, срок жизни, исключения."""

import hashlib
import hmac
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.csrf import (
    generate_csrf_token,
    get_session_id,
    require_csrf,
    validate_csrf_token,
)

_KEY = b"test-signing-key"


def _make_token(ts: int, session_id: str = "default") -> str:
    payload = f"{ts}:{session_id}"
    sig = hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ts}:{session_id}:{sig}"


def test_generate_and_validate():
    token = generate_csrf_token()
    assert validate_csrf_token(token) is True


def test_tampered_signature_rejected():
    token = generate_csrf_token()
    parts = token.split(":")
    parts[2] = "0" * 16
    assert validate_csrf_token(":".join(parts)) is False


def test_wrong_session_rejected():
    token = generate_csrf_token("session-a")
    assert validate_csrf_token(token, "session-b") is False


def test_expired_token_rejected():
    token = _make_token(int(time.time()) - 90000)  # старше 24 часов
    assert validate_csrf_token(token) is False


def test_bad_format_rejected():
    assert validate_csrf_token(None) is False
    assert validate_csrf_token("") is False
    assert validate_csrf_token("not-a-token") is False
    assert validate_csrf_token("1:2:3:4") is False


def test_require_csrf_raises_403():
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"), headers={"user-agent": "test"})
    with pytest.raises(HTTPException) as exc:
        require_csrf(req, None)
    assert exc.value.status_code == 403


def test_require_csrf_ok():
    session_id = hashlib.sha256(b"1.2.3.4:test").hexdigest()[:16]
    token = generate_csrf_token(session_id)
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"), headers={"user-agent": "test"})
    require_csrf(req, token)  # не должно поднять исключение


def test_session_id_deterministic():
    req = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"), headers={"user-agent": "UA"})
    assert get_session_id(req) == get_session_id(req)
    assert len(get_session_id(req)) == 16