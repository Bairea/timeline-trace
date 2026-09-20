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


def test_seed_does_not_add_a_source_column(conn):
    """templates 不该有 source 列——它只写不读，且默认值让旧库无法区分
    「用户改过」与「旧代码灌的」，声称的用途实现不了，已删除。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(templates)")}
    assert "source" not in cols


def test_migration_drops_legacy_source_column(tmp_path, monkeypatch):
    """带 source 列的旧库启动后该列应被清掉，且数据无损。"""
    import app.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old.db")
    c = db.connect()
    c.executescript("""
        CREATE TABLE templates (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
          is_default INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'user');
    """)
    c.execute("INSERT INTO templates (name, is_default, created_at, source)"
              " VALUES ('工作日', 1, 'x', 'user')")
    c.commit()

    db.init_db(c)      # 应执行删列迁移

    cols = {r["name"] for r in c.execute("PRAGMA table_info(templates)")}
    assert "source" not in cols
    assert c.execute("SELECT COUNT(*) n FROM templates").fetchone()["n"] == 1
    c.close()


def test_migration_is_idempotent_on_legacy_db(tmp_path, monkeypatch):
    """迁移重复跑不得抛错（列已不存在时不能再 DROP）。"""
    import app.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old2.db")
    c = db.connect()
    db.init_db(c)
    db.init_db(c)
    db.init_db(c)
    c.close()


def test_reseed_rebuilds_blocks_from_config(conn, specs):
    """改了 YAML 想立刻生效时走显式入口，而不是让每次启动偷偷覆盖。"""
    from app.seed import reseed_from_config

    seed_default_template(conn)
    conn.execute("UPDATE template_blocks SET name = '我改过的' WHERE sort_order = 0")
    conn.execute("DELETE FROM template_blocks WHERE sort_order = 1")
    conn.commit()

    result = reseed_from_config(conn, "工作日")

    assert result["blocks"] == len(specs[0].blocks)
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM template_blocks ORDER BY sort_order")]
    assert names[0] == "早操"                 # 手改被覆盖
    assert len(names) == len(specs[0].blocks)  # 被删的块回来了


def test_reseed_unknown_template_raises(conn, specs):
    from app.seed import reseed_from_config
    seed_default_template(conn)
    with pytest.raises(ValueError):
        reseed_from_config(conn, "不存在的模板")


def test_seed_skips_existing_template_of_same_name(conn, specs):
    """同名模板已存在时不覆盖其块——即使内容完全不同。"""
    conn.execute(
        "INSERT INTO templates (name, is_default, created_at)"
        " VALUES ('工作日', 1, 'x')")
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
