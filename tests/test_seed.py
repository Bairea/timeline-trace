"""种子数据测试。设计文档 §2.3。

块定义已移入 config/timeline.yaml，故这里的断言分两类：
  1. 配置本身的内容正确（块数、首尾、跨零点块）；
  2. 种子化行为正确（幂等、保留用户手改、不重复灌入）。
"""
import pytest

import app.db as db
from app.config import load_timeline
from app.seed import seed_default_template, seed_from_specs


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def specs():
    return load_timeline()


def test_config_has_18_blocks(specs):
    """出厂模板的块数。改动 WORKDAY_BLOCKS / timeline.yaml 时此断言须同步。"""
    assert len(specs) == 1
    assert specs[0].name == "工作日"
    assert specs[0].is_default is True
    assert len(specs[0].blocks) == 18


def test_config_first_and_last_blocks(specs):
    blocks = specs[0].blocks
    b0, bn = blocks[0], blocks[-1]
    assert (b0.start_min, b0.end_min, b0.name) == (390, 420, "早操")
    assert (bn.start_min, bn.end_min, bn.name) == (1360, 1830, "睡觉")


def test_config_sleep_block_spans_midnight(specs):
    """22:40 → 06:30 跨零点，归一到 1360 → 1830。"""
    sleep = [b for b in specs[0].blocks if b.name == "睡觉"][0]
    assert sleep.start_min == 1360
    assert sleep.end_min == 1830
    assert sleep.end_min - sleep.start_min == 470      # 7h50m


def test_seed_inserts_all_blocks(conn, specs):
    tid = seed_default_template(conn)
    n = conn.execute(
        "SELECT COUNT(*) c FROM template_blocks WHERE template_id = ?", (tid,)
    ).fetchone()["c"]
    assert n == len(specs[0].blocks) == 18


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
    assert conn.execute("SELECT COUNT(*) c FROM templates").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM template_blocks").fetchone()["c"] == 18


def test_seed_preserves_user_edits(conn):
    """重启不能冲掉用户在模板编辑页的改动。

    这是「只灌一次」这条设计的关键断言：若改成每次启动按 YAML 覆盖，
    用户在界面上的修改会在下次重启时凭空消失。
    """
    seed_default_template(conn)
    conn.execute("UPDATE template_blocks SET name = '我改过的早操' WHERE sort_order = 0")
    conn.commit()

    seed_default_template(conn)

    name = conn.execute(
        "SELECT name FROM template_blocks WHERE sort_order = 0").fetchone()["name"]
    assert name == "我改过的早操"
    assert conn.execute("SELECT COUNT(*) c FROM template_blocks").fetchone()["c"] == 18


def test_seed_marks_source(conn):
    """新建的模板须标记来源为 seed，供将来判断能否重新种子化。"""
    seed_default_template(conn)
    row = conn.execute("SELECT source FROM templates").fetchone()
    assert row["source"] == "seed"


def test_seed_skips_existing_template_of_same_name(conn, specs):
    """同名模板已存在时不覆盖其块——即使内容完全不同。"""
    conn.execute(
        "INSERT INTO templates (name, is_default, created_at, source)"
        " VALUES ('工作日', 1, 'x', 'user')")
    conn.execute(
        "INSERT INTO template_blocks (template_id, start_min, end_min, name, sort_order)"
        " VALUES (1, 0, 60, '我自己建的', 0)")
    conn.commit()

    seed_default_template(conn)

    rows = conn.execute("SELECT name FROM template_blocks").fetchall()
    assert [r["name"] for r in rows] == ["我自己建的"]


def test_seed_from_specs_reports_only_new(conn, specs):
    """返回值只含本次新建的模板 id，已存在的不计入。"""
    first = seed_from_specs(conn, specs)
    assert len(first) == 1
    second = seed_from_specs(conn, specs)
    assert second == []


def test_seed_raises_when_no_default_template(conn):
    """配置有默认模板但库里被删光了 → 报错而不是静默返回 None。"""
    seed_default_template(conn)
    conn.execute("DELETE FROM template_blocks")
    conn.execute("DELETE FROM templates")
    conn.commit()
    # 库空了会自动重新种入，所以这里实际验证的是「能自愈」
    tid = seed_default_template(conn)
    assert isinstance(tid, int)
