import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setenv("APP_PASSWORD", "testpw")
    import app.auth as auth
    auth._sessions.clear()
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    r = client.post("/api/login", json={"password": "testpw"})
    assert r.status_code == 200
    return client


def test_health_open_without_auth(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["auth_required"] is True


def test_protected_returns_401_without_cookie(client):
    assert client.get("/api/actual?date=2026-09-20").status_code == 401


def test_login_rejects_wrong_password(client):
    r = client.post("/api/login", json={"password": "nope"})
    assert r.status_code == 401


def test_login_then_access(auth_client):
    r = auth_client.get("/api/actual?date=2026-09-20")
    assert r.status_code == 200
    assert r.json() == []


def test_templates_seeded(auth_client):
    r = auth_client.get("/api/templates")
    assert r.status_code == 200
    tpls = r.json()
    assert len(tpls) == 1
    assert tpls[0]["name"] == "工作日"


def test_template_has_18_blocks(auth_client):
    tid = auth_client.get("/api/templates").json()[0]["id"]
    r = auth_client.get(f"/api/templates/{tid}/blocks")
    assert len(r.json()) == 18


def test_quick_record_full_range(auth_client):
    r = auth_client.post("/api/actual/quick",
                         json={"date": "2026-09-20", "line": "20:30-21:10 干活"})
    assert r.status_code == 200
    body = r.json()
    assert (body["start_min"], body["end_min"], body["name"]) == (1230, 1270, "干活")


def test_quick_record_echoes_raw_on_parse_error(auth_client):
    """解析失败必须回显原文，否则用户不知道哪行没被记住。"""
    r = auth_client.post("/api/actual/quick",
                         json={"date": "2026-09-20", "line": "这不是时间"})
    assert r.status_code == 422
    assert r.json()["raw"] == "这不是时间"


def test_quick_record_open_range(auth_client):
    r = auth_client.post("/api/actual/quick",
                         json={"date": "2026-09-20", "line": "20:30- 干活"})
    assert r.status_code == 200
    assert r.json()["end_min"] is None


def test_delete_then_restore(auth_client):
    r = auth_client.post("/api/actual/quick",
                         json={"date": "2026-09-20", "line": "20:30-21:10 干活"})
    bid = r.json()["id"]
    assert auth_client.delete(f"/api/actual/{bid}").status_code == 200
    assert auth_client.get("/api/actual?date=2026-09-20").json() == []
    auth_client.post(f"/api/actual/{bid}/restore")
    assert len(auth_client.get("/api/actual?date=2026-09-20").json()) == 1


def test_update_rejects_empty_name(auth_client):
    r = auth_client.post("/api/actual/quick",
                         json={"date": "2026-09-20", "line": "20:30-21:10 干活"})
    bid = r.json()["id"]
    assert auth_client.put(f"/api/actual/{bid}", json={"name": "  "}).status_code == 422


def test_delete_missing_block_404(auth_client):
    assert auth_client.delete("/api/actual/99999").status_code == 404


def test_compare_endpoint(auth_client):
    auth_client.post("/api/actual/quick",
                     json={"date": "2026-09-20", "line": "06:35-07:02 早操"})
    r = auth_client.get("/api/compare?date=2026-09-20")
    assert r.status_code == 200
    rows = r.json()["rows"]
    early = [x for x in rows if x["template_name"] == "早操"]
    assert early[0]["status"] == "aligned"


def test_compare_unrecorded_when_nothing_recorded(auth_client):
    r = auth_client.get("/api/compare?date=2026-09-20")
    statuses = {x["status"] for x in r.json()["rows"]}
    assert statuses == {"unrecorded"}


def test_no_password_means_open_access(tmp_path, monkeypatch):
    """未设 APP_PASSWORD 时本地开发免登录。"""
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    import app.auth as auth
    auth._sessions.clear()
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/actual?date=2026-09-20").status_code == 200
