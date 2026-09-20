"""对照与报告接口。设计文档 §4/§8。"""
from fastapi import APIRouter, Depends, HTTPException

from app import db, repo
from app.auth import require_session
from app.compare import compare_day

router = APIRouter(prefix="/api", tags=["reports"],
                   dependencies=[Depends(require_session)])


def _conn():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


@router.get("/compare")
def compare(date: str, conn=Depends(_conn)):
    """某日对照结果。模板取默认工作日模板。"""
    tpl = conn.execute(
        "SELECT * FROM templates WHERE is_default = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not tpl:
        raise HTTPException(404, "没有默认模板")

    tpl_blocks = repo.to_block_likes(repo.list_template_blocks(conn, tpl["id"]))
    act_blocks = repo.to_block_likes(repo.list_actual(conn, date))

    results = compare_day(tpl_blocks, act_blocks)
    return {
        "date": date,
        "template_id": tpl["id"],
        "template_name": tpl["name"],
        "rows": [
            {
                "template_name": r.template_name,
                "actual_name": r.actual_name,
                "template_start": r.template_start,
                "template_end": r.template_end,
                "actual_start": r.actual_start,
                "actual_end": r.actual_end,
                "status": r.status,
                "overlap_min": r.overlap_min,
                "delta_start_min": r.delta_start_min,
                "delta_dur_min": r.delta_dur_min,
            }
            for r in results
        ],
    }
