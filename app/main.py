"""FastAPI 应用骨架。设计文档 §4。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app import auth, db
from app.api import actual, reports, templates

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    from app.seed import seed_default_template
    seed_default_template(conn)
    conn.close()
    yield


class AuthMiddleware:
    """纯 ASGI 鉴权，不能用 BaseHTTPMiddleware。

    `@app.middleware("http")` 会把下游拆进另一个任务。同步接口的 SQLite
    连接由依赖创建、由依赖退出时关闭，这两步会被拆到不同线程，触发
    "SQLite objects created in a thread can only be used in that same thread"。
    首页同时请求模板、对照、实际块时就会 500，理想轴因此空白。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if auth.auth_enabled() and path.startswith("/api"):
            if not any(path.startswith(p) for p in auth.PUBLIC_PATHS):
                cookie = _cookie(scope, auth.COOKIE_NAME)
                if not auth.is_valid(cookie):
                    response = JSONResponse(
                        {"detail": "未授权，请先登录"}, status_code=401)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _cookie(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == name:
                    return v
    return None


app = FastAPI(title="timeline-trace", lifespan=lifespan)
app.add_middleware(AuthMiddleware)


@app.get("/api/health")
def health():
    return {"ok": True, "auth_required": auth.auth_enabled()}


@app.post("/api/login")
def login(payload: dict, response: Response):
    if not auth.verify_password(payload.get("password", "")):
        return JSONResponse({"detail": "口令错误"}, status_code=401)
    token = auth.create_session()
    auth.set_session_cookie(response, token)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


app.include_router(templates.router)
app.include_router(actual.router)
app.include_router(reports.router)


@app.get("/")
def index():
    f = STATIC_DIR / "index.html"
    if f.exists():
        return FileResponse(f)
    return JSONResponse({"detail": "前端未构建"}, status_code=404)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
