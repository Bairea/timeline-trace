"""访问口令认证。设计文档 §9.4。

单人自用，单个口令 + HttpOnly Cookie 足够。公网 IP 会在数小时内被
扫描器发现，因此认证不是可选项。
"""
import os
import secrets
from typing import Optional

from fastapi import Cookie, HTTPException, Response

COOKIE_NAME = "tt_session"
SESSION_TTL_DAYS = 30

# 进程内会话表：token -> 无（存在即有效）
_sessions: set[str] = set()

# 无需认证即可访问的路径（前缀匹配）
PUBLIC_PATHS = (
    "/api/login",
    "/api/health",
    "/login",
)


def _password() -> str:
    return os.environ.get("APP_PASSWORD", "")


def auth_enabled() -> bool:
    """未设口令时（本地开发）自动放行，避免开发被挡。"""
    return bool(_password())


def verify_password(candidate: str) -> bool:
    expected = _password()
    if not expected:
        return True
    return secrets.compare_digest(candidate, expected)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    return token


def drop_session(token: str) -> None:
    _sessions.discard(token)


def is_valid(token: Optional[str]) -> bool:
    if not auth_enabled():
        return True
    return bool(token) and token in _sessions


def require_session(tt_session: Optional[str] = Cookie(default=None)) -> None:
    """FastAPI 依赖：校验会话，失败抛 401。"""
    if not is_valid(tt_session):
        raise HTTPException(status_code=401, detail="未授权，请先登录")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("APP_COOKIE_SECURE", "0") == "1",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
    )
