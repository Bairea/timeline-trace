import pytest

import app.db as db
from app import repo


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    db.init_db(c)
    yield c
    c.close()


def test_insert_and_list(conn):
    repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    rows = repo.list_actual(conn, "2026-09-20")
    assert len(rows) == 1
    assert rows[0]["name"] == "干活"
    assert rows[0]["end_min"] == 1270


def test_list_filters_other_dates(conn):
    repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.insert_actual(conn, "2026-09-21", 1230, 1270, "干活")
    assert len(repo.list_actual(conn, "2026-09-20")) == 1


def test_list_orders_by_start(conn):
    repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.insert_actual(conn, "2026-09-20", 390, 420, "早操")
    rows = repo.list_actual(conn, "2026-09-20")
    assert [r["name"] for r in rows] == ["早操", "干活"]


def test_soft_delete_hides_from_list(conn):
    bid = repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.soft_delete_actual(conn, bid)
    assert repo.list_actual(conn, "2026-09-20") == []


def test_soft_deleted_row_still_in_table(conn):
    """软删除必须是可追溯的——行不能被物理删除。"""
    bid = repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.soft_delete_actual(conn, bid)
    raw = conn.execute("SELECT deleted_at FROM actual_blocks WHERE id = ?", (bid,)).fetchone()
    assert raw is not None
    assert raw["deleted_at"] is not None


def test_restore_brings_it_back(conn):
    bid = repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.soft_delete_actual(conn, bid)
    repo.restore_actual(conn, bid)
    rows = repo.list_actual(conn, "2026-09-20")
    assert len(rows) == 1
    assert rows[0]["name"] == "干活"


def test_update_fields(conn):
    bid = repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.update_actual(conn, bid, end_min=1320, name="干活（延长）")
    row = repo.get_actual(conn, bid)
    assert row["end_min"] == 1320
    assert row["name"] == "干活（延长）"


def test_update_ignores_unknown_fields(conn):
    bid = repo.insert_actual(conn, "2026-09-20", 1230, 1270, "干活")
    repo.update_actual(conn, bid, date="2020-01-01", bogus=1)  # 应被忽略
    row = repo.get_actual(conn, bid)
    assert row["date"] == "2026-09-20"


def test_update_low_stimulus_flag(conn):
    bid = repo.insert_actual(conn, "2026-09-20", 1215, 1230, "读书")
    repo.update_actual(conn, bid, is_low_stimulus=True)
    assert repo.get_actual(conn, bid)["is_low_stimulus"] == 1


def test_open_range_stored_as_null(conn):
    repo.insert_actual(conn, "2026-09-20", 1230, None, "干活")
    row = repo.list_actual(conn, "2026-09-20")[0]
    assert row["end_min"] is None


def test_to_block_likes_skips_open_ranges(conn):
    repo.insert_actual(conn, "2026-09-20", 1230, None, "干活")
    repo.insert_actual(conn, "2026-09-20", 390, 420, "早操")
    likes = repo.to_block_likes(repo.list_actual(conn, "2026-09-20"))
    assert len(likes) == 1
    assert likes[0].name == "早操"
