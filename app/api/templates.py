"""模板接口。设计文档 §4。"""
from fastapi import APIRouter, Depends, HTTPException

from app import db, repo
from app.auth import require_session

router = APIRouter(prefix="/api", tags=["templates"],
                   dependencies=[Depends(require_session)])


def _conn():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


@router.get("/templates")
def list_templates(conn=Depends(_conn)):
    rows = conn.execute(
        "SELECT * FROM templates ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@router.get("/templates/{template_id}/blocks")
def get_template_blocks(template_id: int, conn=Depends(_conn)):
    tpl = conn.execute(
        "SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if not tpl:
        raise HTTPException(404, "模板不存在")
    return repo.list_template_blocks(conn, template_id)


@router.post("/templates/{template_id}/blocks")
def add_template_block(template_id: int, payload: dict, conn=Depends(_conn)):
    tpl = conn.execute(
        "SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if not tpl:
        raise HTTPException(404, "模板不存在")
    start = payload.get("start_min")
    end = payload.get("end_min")
    name = (payload.get("name") or "").strip()
    if start is None or end is None or not name:
        raise HTTPException(422, "start_min / end_min / name 均为必填")
    if end <= start:
        end += 24 * 60
    nxt = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM template_blocks"
        " WHERE template_id = ?", (template_id,)).fetchone()["n"]
    cur = conn.execute(
        "INSERT INTO template_blocks"
        " (template_id, start_min, end_min, name, category, sort_order)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (template_id, start, end, name, payload.get("category"), nxt))
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/template-blocks/{block_id}")
def update_template_block(block_id: int, payload: dict, conn=Depends(_conn)):
    row = conn.execute(
        "SELECT * FROM template_blocks WHERE id = ?", (block_id,)).fetchone()
    if not row:
        raise HTTPException(404, "模板块不存在")
    allowed = {"start_min", "end_min", "name", "category", "sort_order"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        return {"ok": True}
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE template_blocks SET {sets} WHERE id = ?",
                 (*updates.values(), block_id))
    conn.commit()
    return {"ok": True}


@router.delete("/template-blocks/{block_id}")
def delete_template_block(block_id: int, conn=Depends(_conn)):
    conn.execute("DELETE FROM template_blocks WHERE id = ?", (block_id,))
    conn.commit()
    return {"ok": True}
