"""FastAPI 应用骨架。设计文档 §4。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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


app = FastAPI(title="timeline-trace", lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if auth.auth_enabled() and path.startswith("/api"):
        if not any(path.startswith(p) for p in auth.PUBLIC_PATHS):
            if not auth.is_valid(request.cookies.get(auth.COOKIE_NAME)):
                return JSONResponse({"detail": "未授权，请先登录"}, status_code=401)
    return await call_next(request)


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
