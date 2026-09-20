import pytest

import app.db as db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    db.init_db(c)
    yield c
    c.close()


def test_init_db_creates_all_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"templates", "template_blocks", "day_instances", "actual_blocks"} <= names


def test_init_db_is_idempotent(conn):
    db.init_db(conn)  # 不应抛错
    db.init_db(conn)


def test_actual_blocks_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(actual_blocks)")}
    assert {"date", "start_min", "end_min", "name", "is_low_stimulus",
            "created_at", "updated_at", "deleted_at"} <= cols


def test_end_min_is_nullable_for_open_range(conn):
    conn.execute(
        "INSERT INTO actual_blocks (date,start_min,end_min,name,created_at,updated_at)"
        " VALUES ('2026-09-20',1230,NULL,'干活','x','x')")
    row = conn.execute("SELECT end_min FROM actual_blocks").fetchone()
    assert row["end_min"] is None
