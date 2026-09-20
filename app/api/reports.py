"""对照、统计与导出接口。设计文档 §4/§8。"""
from datetime import date as date_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response

from app import db, repo
from app.auth import require_session
from app.classify import infer_category_map
from app.compare import compare_day
from app.config import load_thresholds
from app.export import (export_csv, export_csv_actual, export_xlsx,
                        rows_actual, rows_template)
from app.stats import daily_summary, range_stats

router = APIRouter(prefix="/api", tags=["reports"],
                   dependencies=[Depends(require_session)])


def _conn():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


def _compare_for(conn, date: str):
    """取某日的模板块、对照结果、实际块，以及实际块的分类映射。

    第 4 项（categories）是本次新增的：优先级四项的判定依赖实际块的
    category，而实际块表没有这一列，故由 classify 从模板派生。
    在这里一次算好往下传，避免 stats 反复查库。
    """
    tpl = conn.execute(
        "SELECT * FROM templates WHERE is_default = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not tpl:
        raise HTTPException(404, "没有默认模板")

    tpl_rows = repo.list_template_blocks(conn, tpl["id"])
    tpl_blocks = repo.to_block_likes(tpl_rows)
    actual_rows = repo.list_actual(conn, date)
    act_blocks = repo.to_block_likes(actual_rows)
    categories = infer_category_map(actual_rows, tpl_rows)
    return tpl, compare_day(tpl_blocks, act_blocks), actual_rows, categories


@router.get("/compare")
def compare(date: str, conn=Depends(_conn)):
    """某日对照结果。模板取默认工作日模板。"""
    tpl, results = _compare_for(conn, date)[:2]
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


def _date_range(start: str, end: str) -> list[str]:
    d0 = date_cls.fromisoformat(start)
    d1 = date_cls.fromisoformat(end)
    if d1 < d0:
        raise HTTPException(422, "end 不能早于 start")
    if (d1 - d0).days > 366:
        raise HTTPException(422, "区间过长（上限 366 天）")
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


@router.get("/stats")
def stats(start: str, end: str, conn=Depends(_conn)):
    thresholds = load_thresholds()
    days = []
    summaries = []
    all_categories: dict[str, dict[int, str]] = {}
    for d in _date_range(start, end):
        _, results, actual_rows, categories = _compare_for(conn, d)
        days.append({"date": d, "rows": results, "actual_rows": actual_rows})
        all_categories[d] = categories
        summaries.append(daily_summary(d, results, actual_rows))
    return {"start": start, "end": end,
            "daily": summaries,
            "range": range_stats(days, thresholds, all_categories)}


@router.get("/export")
def export(start: str, end: str, format: str = "csv", scope: str = "both",
           conn=Depends(_conn)):
    """导出每日每段的精确分配。设计文档 §8（方案 B）。

    scope=actual 只出实际明细（可安全求和）；both 额外附模板对照段。
    """
    if format not in ("csv", "xlsx"):
        raise HTTPException(422, "format 只能是 csv 或 xlsx")
    if scope not in ("actual", "both"):
        raise HTTPException(422, "scope 只能是 actual 或 both")

    act_rows: list[list] = []
    tpl_rows: list[list] = []
    summaries: list[list] = []
    days = []
    all_categories: dict[str, dict[int, str]] = {}
    for d in _date_range(start, end):
        _, results, actual_rows, categories = _compare_for(conn, d)
        act_rows.extend(rows_actual(d, results, actual_rows))
        tpl_rows.extend(rows_template(d, results))
        summaries.append(daily_summary(d, results, actual_rows))
        days.append({"date": d, "rows": results, "actual_rows": actual_rows})
        all_categories[d] = categories

    if format == "csv":
        body = (export_csv_actual(act_rows) if scope == "actual"
                else export_csv(act_rows, tpl_rows))
        return Response(
            content=body.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="timeline_{start}_{end}.csv"'},
        )

    body = export_xlsx(act_rows, tpl_rows, summaries,
                       range_stats(days, load_thresholds(), all_categories))
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="timeline_{start}_{end}.xlsx"'},
    )
