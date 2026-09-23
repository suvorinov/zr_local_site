"""CSRF-защита для форм.

Реализует токен-based CSRF-защиту через signed cookie.
При GET-запросе генерирует токен, при POST — проверяет.
"""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request, status

# Секрет для подписи токенов — генерируется при старте приложения.
# Достаточно стабилен между перезапусками (храним в файле или env).
_signing_key: str | None = None


def _get_signing_key() -> str:
    """Возвращает ключ подписи. Создаёт файл-секрет при первом запуске."""
    global _signing_key
    if _signing_key is not None:
        return _signing_key

    secret_path = os.environ.get("CORP_CSRF_SECRET_FILE", ".csrf_secret")
    if os.path.exists(secret_path):
        _signing_key = open(secret_path).read().strip()
    else:
        _signing_key = secrets.token_hex(32)
        with open(secret_path, "w") as f:
            f.write(_signing_key)
    return _signing_key


def generate_csrf_token(session_id: str = "default") -> str:
    """Генерирует подписанный CSRF-токен.

    Токен = timestamp + hmac-подпись. Валиден 24 часа.

    Args:
        session_id: Идентификатор сессии (для привязки токена).

    Returns:
        Строка токена.
    """
    key = _get_signing_key()
    ts = str(int(time.time()))
    payload = f"{ts}:{session_id}"
    sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    token = f"{ts}:{session_id}:{sig}"
    return token


def validate_csrf_token(token: str | None, session_id: str = "default") -> bool:
    """Проверяет CSRF-токен.

    Args:
        token: Токен из формы.
        session_id: Идентификатор сессии для проверки.

    Returns:
        True если токен валиден, иначе False.
    """
    if not token:
        return False

    key = _get_signing_key()
    parts = token.split(":")
    if len(parts) != 3:
        return False

    ts_str, sid, sig = parts

    # Проверяем что сессия совпадает
    if sid != session_id:
        return False

    # Проверяем подпись
    payload = f"{ts_str}:{sid}"
    expected_sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected_sig):
        return False

    # Проверяем срок жизни (24 часа)
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if time.time() - ts > 86400:
        return False

    return True


def get_session_id(request: Request) -> str:
    """Вычисляет session ID по IP + User-Agent для привязки CSRF.

    Args:
        request: Объект запроса.

    Returns:
        Строка-идентификатор сессии (первые 16 символов SHA-256).
    """
    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{client_ip}:{ua}".encode()).hexdigest()[:16]


def require_csrf(request: Request, token: str | None) -> None:
    """Проверяет CSRF-токен и выбрасывает 403 если невалиден.

    Args:
        request: Объект запроса.
        token: Токен из формы.

    Raises:
        HTTPException: 403 если токен невалиден.
    """
    session_id = get_session_id(request)
    if not validate_csrf_token(token, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF-токен невалидный. Обновите страницу и попробуйте снова.",
        )
