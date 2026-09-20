"""SQLite 连接与建表。设计文档 §3。"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "timeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  is_default  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS template_blocks (
  id          INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  start_min   INTEGER NOT NULL,
  end_min     INTEGER NOT NULL,
  name        TEXT NOT NULL,
  category    TEXT,
  sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS day_instances (
  date        TEXT PRIMARY KEY,
  template_id INTEGER REFERENCES templates(id),
  note        TEXT
);
CREATE TABLE IF NOT EXISTS actual_blocks (
  id               INTEGER PRIMARY KEY,
  date             TEXT NOT NULL,
  start_min        INTEGER NOT NULL,
  end_min          INTEGER,
  name             TEXT NOT NULL,
  is_low_stimulus  INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  deleted_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_actual_date
  ON actual_blocks(date) WHERE deleted_at IS NULL;
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


# 幂等迁移。SCHEMA 里全是 CREATE TABLE IF NOT EXISTS，对已存在的表
# 加不了列——已上线的库需要单独补。每条迁移都先探测再执行，重复跑无副作用。
_ADD_COLUMNS: list[tuple[str, str, str]] = []

# 要删除的列：(表名, 列名)。SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN。
#
# templates.source 是「YAML 配置化」时加的，本意是区分「配置灌的」与
# 「用户改的」，好判断能否重新种子化。但它的默认值是 'user'，意味着任何
# 从旧版本升级上来的库都会被标成 user——区分不出「用户真改过」和
# 「旧代码灌的」，声称的用途根本实现不了。而实际判断是否灌入用的是
# 模板名，从没读过这一列。只写不读 + 语义不可用 = 纯技术债，删掉。
#
# 教训：加字段前先想清楚「谁读它、读到之后做什么」。想不出来的话，
# 那个字段本身就是答案。
_DROP_COLUMNS: list[tuple[str, str]] = [
    ("templates", "source"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _ADD_COLUMNS:
        if column not in _columns(conn, table):
            conn.execute(ddl)
    for table, column in _DROP_COLUMNS:
        if column in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
