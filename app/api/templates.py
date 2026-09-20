"""模板接口。设计文档 §4/§6.3。

写入路径的校验规则（POST 与 PUT 共用同一套，见 `_validate`）：
只校验创建而不校验修改，等于把校验漏了一半——改一次就能绕过。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app import db, repo
from app.auth import require_session
from app.compare import DAY_MIN

router = APIRouter(prefix="/api", tags=["templates"],
                   dependencies=[Depends(require_session)])


def _conn():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


def _validate(start: object, end: object, name: object) -> tuple[int, int, str]:
    """模板块的时间与名称校验。返回 (start, end, name)。

    与快速记录解析器的取舍**刻意不同**：那里结束早于开始视为跨零点
    （白天随手敲，猜的代价低）；这里结束早于开始判为敲错并拒绝，
    因为模板编辑是坐在电脑前刻意做的操作，替用户猜意图反而危险。
    """
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(422, "名称不能为空")
    if not isinstance(start, int) or not isinstance(end, int):
        raise HTTPException(422, "start_min / end_min 必须是整数分钟")
    if not (0 <= start <= DAY_MIN) or not (0 <= end <= DAY_MIN):
        raise HTTPException(422, f"时间须落在 0–{DAY_MIN} 分钟（00:00–24:00）")
    if end <= start:
        raise HTTPException(422, "结束时间必须晚于开始时间")
    return start, end, name.strip()


def _fetch_block(conn, block_id: int):
    row = conn.execute(
        "SELECT * FROM template_blocks WHERE id = ?", (block_id,)).fetchone()
    if not row:
        raise HTTPException(404, "模板块不存在")
    return row


def _fetch_template(conn, template_id: int):
    row = conn.execute(
        "SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        raise HTTPException(404, "模板不存在")
    return row


@router.get("/templates")
def list_templates(conn=Depends(_conn)):
    rows = conn.execute(
        "SELECT * FROM templates ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@router.get("/templates/{template_id}/blocks")
def get_template_blocks(template_id: int, conn=Depends(_conn)):
    _fetch_template(conn, template_id)
    return repo.list_template_blocks(conn, template_id)


@router.post("/templates/{template_id}/blocks")
def add_template_block(template_id: int, payload: dict, conn=Depends(_conn)):
    _fetch_template(conn, template_id)
    start, end, name = _validate(
        payload.get("start_min"), payload.get("end_min"), payload.get("name"))

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
    """局部更新。start / end / name 三者取「新值或原值」后整体校验，
    否则只改 end 就能绕过 start<end 的约束。"""
    row = _fetch_block(conn, block_id)

    allowed = {"start_min", "end_min", "name", "category", "sort_order"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        return {"ok": True}

    if {"start_min", "end_min", "name"} & updates.keys():
        start, end, name = _validate(
            updates.get("start_min", row["start_min"]),
            updates.get("end_min", row["end_min"]),
            updates.get("name", row["name"]),
        )
        updates["start_min"], updates["end_min"], updates["name"] = start, end, name

    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE template_blocks SET {sets} WHERE id = ?",
                 (*updates.values(), block_id))
    conn.commit()
    return {"ok": True}


@router.delete("/template-blocks/{block_id}")
def delete_template_block(block_id: int, conn=Depends(_conn)):
    """硬删除。

    与 actual_blocks 的软删除**语义不同**：实际块保留 deleted_at 是为了
    「上周三删错了」能追溯；模板块是比对基准线，删掉就是少了一格，
    历史日报按新模板重算即可，留墓碑反而让基准线变得难以解释。

    设计文档 §6.3 要求「模板块不能随手删，须进模板编辑页」——本接口
    只保证删除是**显式的一次调用**，多一道手续由界面承担
    （见 static/template.html 的二次确认）。
    """
    _fetch_block(conn, block_id)
    conn.execute("DELETE FROM template_blocks WHERE id = ?", (block_id,))
    conn.commit()
    return {"ok": True}
