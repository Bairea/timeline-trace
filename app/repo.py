"""实际块的数据访问。所有查询自动过滤软删除。设计文档 §3/§6.3。"""
import sqlite3
from datetime import datetime
from typing import Any, Optional

from app.compare import BlockLike


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def insert_actual(conn: sqlite3.Connection, date: str, start_min: int,
                  end_min: Optional[int], name: str,
                  is_low_stimulus: bool = False) -> int:
    ts = _now()
    cur = conn.execute(
        "INSERT INTO actual_blocks"
        " (date, start_min, end_min, name, is_low_stimulus, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (date, start_min, end_min, name, int(is_low_stimulus), ts, ts),
    )
    conn.commit()
    return cur.lastrowid


def update_actual(conn: sqlite3.Connection, block_id: int, **fields: Any) -> None:
    allowed = {"start_min", "end_min", "name", "is_low_stimulus"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    if "is_low_stimulus" in updates:
        updates["is_low_stimulus"] = int(bool(updates["is_low_stimulus"]))
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE actual_blocks SET {sets}, updated_at = ? WHERE id = ?",
        (*updates.values(), _now(), block_id),
    )
    conn.commit()


def soft_delete_actual(conn: sqlite3.Connection, block_id: int) -> None:
    """软删除：写 deleted_at，行仍保留以便事后追溯。"""
    conn.execute(
        "UPDATE actual_blocks SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (_now(), _now(), block_id),
    )
    conn.commit()


def restore_actual(conn: sqlite3.Connection, block_id: int) -> None:
    """撤销删除。"""
    conn.execute(
        "UPDATE actual_blocks SET deleted_at = NULL, updated_at = ? WHERE id = ?",
        (_now(), block_id),
    )
    conn.commit()


def list_actual(conn: sqlite3.Connection, date: str) -> list[dict]:
    """列出某日有效实际块，按起始时间排序。自动过滤软删除。"""
    rows = conn.execute(
        "SELECT * FROM actual_blocks"
        " WHERE date = ? AND deleted_at IS NULL"
        " ORDER BY start_min",
        (date,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_actual(conn: sqlite3.Connection, block_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM actual_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    return dict(row) if row else None


def list_template_blocks(conn: sqlite3.Connection, template_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM template_blocks WHERE template_id = ? ORDER BY sort_order",
        (template_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def to_block_likes(rows: list[dict]) -> list[BlockLike]:
    """把数据库行转成对照引擎的输入。跳过未闭合（end_min 为空）的块。"""
    out = []
    for r in rows:
        if r.get("end_min") is None:
            continue
        out.append(BlockLike(r["start_min"], r["end_min"], r["name"]))
    return out
