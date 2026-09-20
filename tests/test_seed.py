import pytest

import app.db as db
from app.seed import seed_default_template, WORKDAY_BLOCKS


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    db.init_db(c)
    yield c
    c.close()


def test_seed_inserts_all_blocks(conn):
    tid = seed_default_template(conn)
    n = conn.execute(
        "SELECT COUNT(*) c FROM template_blocks WHERE template_id = ?", (tid,)
    ).fetchone()["c"]
    assert n == len(WORKDAY_BLOCKS) == 18


def test_seed_first_and_last_blocks(conn):
    tid = seed_default_template(conn)
    rows = conn.execute(
        "SELECT start_min, end_min, name FROM template_blocks"
        " WHERE template_id = ? ORDER BY sort_order", (tid,)
    ).fetchall()
    assert (rows[0]["start_min"], rows[0]["end_min"], rows[0]["name"]) == (390, 420, "早操")
    assert (rows[-1]["start_min"], rows[-1]["end_min"], rows[-1]["name"]) == (1360, 1830, "睡觉")


def test_seed_is_idempotent(conn):
    tid1 = seed_default_template(conn)
    tid2 = seed_default_template(conn)
    assert tid1 == tid2
    n = conn.execute("SELECT COUNT(*) c FROM templates").fetchone()["c"]
    assert n == 1


def test_sleep_block_spans_midnight(conn):
    tid = seed_default_template(conn)
    row = conn.execute(
        "SELECT start_min, end_min FROM template_blocks"
        " WHERE template_id = ? AND name = '睡觉'", (tid,)
    ).fetchone()
    assert row["start_min"] == 1360          # 22:40
    assert row["end_min"] == 1830            # 次日 06:30
    # 跨零点时长 470 分钟 = 7h50m
    assert row["end_min"] - row["start_min"] == 470
