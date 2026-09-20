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
    conn.commit()
