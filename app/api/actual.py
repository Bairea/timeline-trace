"""实际块接口，含快速记录。设计文档 §6/§7。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app import db, repo
from app.auth import require_session
from app.parser import ParseError, parse_line

router = APIRouter(prefix="/api", tags=["actual"],
                   dependencies=[Depends(require_session)])


def _conn():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


@router.get("/actual")
def list_actual(date: str, conn=Depends(_conn)):
    return repo.list_actual(conn, date)


@router.post("/actual/quick")
def quick_record(payload: dict, conn=Depends(_conn)):
    """快速记录。解析失败返回 422 并回显原始文本（设计文档 §7.3）。"""
    date = payload.get("date")
    line = payload.get("line", "")
    if not date:
        raise HTTPException(422, "缺少 date")

    rows = repo.list_actual(conn, date)
    prev_end = None
    for r in rows:
        if r["end_min"] is not None and (prev_end is None or r["end_min"] > prev_end):
            prev_end = r["end_min"]

    now_min = datetime.now().hour * 60 + datetime.now().minute

    try:
        parsed = parse_line(line, prev_end=prev_end, now_min=now_min)
    except ParseError as e:
        # 必须回显原始文本，否则用户不知道哪一行没被记住
        return _unprocessable(str(e), raw=line)

    block_id = repo.insert_actual(conn, date, parsed.start_min,
                                  parsed.end_min, parsed.name)
    return {"id": block_id, "date": date, "start_min": parsed.start_min,
            "end_min": parsed.end_min, "name": parsed.name}


def _unprocessable(detail: str, raw: str):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": detail, "raw": raw}, status_code=422)


@router.put("/actual/{block_id}")
def update_actual(block_id: int, payload: dict, conn=Depends(_conn)):
    if not repo.get_actual(conn, block_id):
        raise HTTPException(404, "块不存在")
    if "name" in payload and not str(payload["name"]).strip():
        raise HTTPException(422, "名称不能为空")
    repo.update_actual(conn, block_id, **payload)
    return repo.get_actual(conn, block_id)


@router.delete("/actual/{block_id}")
def delete_actual(block_id: int, conn=Depends(_conn)):
    """软删除，可撤销。"""
    if not repo.get_actual(conn, block_id):
        raise HTTPException(404, "块不存在")
    repo.soft_delete_actual(conn, block_id)
    return {"ok": True, "id": block_id}


@router.post("/actual/{block_id}/restore")
def restore_actual(block_id: int, conn=Depends(_conn)):
    if not repo.get_actual(conn, block_id):
        raise HTTPException(404, "块不存在")
    repo.restore_actual(conn, block_id)
    return {"ok": True, "id": block_id}
