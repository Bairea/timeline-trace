"""CSV / XLSX 导出。设计文档 §8（方案 B：双表）。

两张表语义不同，不可混用：

- **实际明细**（rows_actual）：每个实际块一行。`duration_min` 求和
  精确等于当日记录总时长，可安全在 Excel 里直接求和。一个实际块
  即使命中多个模板块，也只出一行。
- **模板对照**（rows_template）：每个模板块一行，含 `unrecorded`。
  用于回答「模板哪些块没做到」，**不可对时长求和**（模板块本就
  可能重叠或留白）。

时间以分钟数存储，导出时还原为 HH:MM。跨零点（> 1440）还原为次日
的 HH:MM，避免 Excel 里出现 30:30 这种非法值。
"""
import csv
import io
from typing import Iterable, Optional

from openpyxl import Workbook

ACTUAL_HEADER = [
    "date", "start", "end", "duration_min", "block_name",
    "matched_template", "status", "delta_start_min", "delta_dur_min", "is_planned",
]

TEMPLATE_HEADER = [
    "date", "template_start", "template_end", "template_duration_min",
    "template_block", "actual_block", "status",
    "delta_start_min", "delta_dur_min",
]

DAILY_HEADER = ["date", "recorded_min", "unplanned_min", "aligned", "offset",
                "unrecorded", "unplanned"]


def fmt_min(m: Optional[int]) -> str:
    """分钟数 → HH:MM。跨零点还原为次日时刻（1830 → 06:30）。"""
    if m is None:
        return ""
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def _norm_actual(r) -> tuple[int, Optional[int], str]:
    """接受数据库行（dict）或 BlockLike，统一成 (start, end, name)。"""
    if isinstance(r, dict):
        return r["start_min"], r.get("end_min"), r["name"]
    return r.start_min, r.end_min, r.name


def rows_actual(date: str, comparisons: Iterable, actual_rows: list) -> list[list]:
    """实际明细：每个实际块一行，可直接求和。

    优先使用 actual_rows（数据库原始行，含未闭合块），缺失时回退到
    对照结果中的实际块。未被任何模板块引用的块也要出现。
    """
    # 收集对照结果中每个实际块的最佳匹配（按 (start,end,name) 归并）
    best: dict[tuple, tuple] = {}
    for c in comparisons:
        if c.actual_start is None or c.actual_end is None:
            continue
        key = (c.actual_start, c.actual_end, c.actual_name)
        if c.status == "unplanned":
            continue
        prev = best.get(key)
        if prev is None or _rank_status(c.status) > _rank_status(prev[0]):
            best[key] = (c.status, c.template_name, c.delta_start_min, c.delta_dur_min)

    unplanned_keys = {
        (c.actual_start, c.actual_end, c.actual_name)
        for c in comparisons
        if c.status == "unplanned" and c.actual_start is not None
    }

    out = []
    for raw in actual_rows:
        start, end, name = _norm_actual(raw)
        key = (start, end, name)

        if key in unplanned_keys:
            status, matched, ds, dd = "unplanned", "", "", ""
        else:
            found = best.get(key)
            if found:
                status, matched, ds, dd = found
                ds = "" if ds is None else str(ds)
                dd = "" if dd is None else str(dd)
            else:
                # 未闭合或无匹配 → offset（有交集但非计划外）
                status, matched, ds, dd = "offset", "", "", ""

        out.append([
            date,
            fmt_min(start),
            fmt_min(end),
            "" if end is None else str(end - start),
            name,
            matched or "",
            status,
            ds, dd,
            "true" if status == "unplanned" else "false",
        ])

    out.sort(key=lambda x: x[1])
    return out


_RANK_STATUS = {"unrecorded": 0, "offset": 1, "aligned": 2, "unplanned": 3}


def _rank_status(s: str) -> int:
    return _RANK_STATUS.get(s, 0)


def rows_template(date: str, comparisons: Iterable) -> list[list]:
    """模板对照：每个模板块一行，含 unrecorded。不含 unplanned。

    「落败的实际块」行（template_name 非空但非该模板块的最优结果，
    即 compare_day 为防数据丢失而补齐的行）不在此表重复出现——
    该表以模板块为唯一键，一个模板块只出一行。
    """
    seen_templates: set[tuple] = set()
    out = []
    for c in comparisons:
        if c.status == "unplanned":
            continue
        if c.template_start is None:
            continue
        key = (c.template_start, c.template_end, c.template_name)
        if key in seen_templates:
            continue
        seen_templates.add(key)

        t_start, t_end = c.template_start, c.template_end
        out.append([
            date,
            fmt_min(t_start),
            fmt_min(t_end),
            "" if (t_start is None or t_end is None) else str(t_end - t_start),
            c.template_name or "",
            c.actual_name or "",
            c.status,
            "" if c.delta_start_min is None else str(c.delta_start_min),
            "" if c.delta_dur_min is None else str(c.delta_dur_min),
        ])
    out.sort(key=lambda x: x[1])
    return out


def export_csv(actual_section: list[list],
               template_section: list[list] | None = None) -> str:
    """UTF-8 BOM 前缀，Excel 双击可直接打开且不乱码。

    两段用空行分隔：第一段实际明细（可求和），第二段模板对照。
    """
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ACTUAL_HEADER)
    w.writerows(actual_section)
    if template_section is not None:
        w.writerow([])
        w.writerow(TEMPLATE_HEADER)
        w.writerows(template_section)
    return "\ufeff" + buf.getvalue()


def export_csv_actual(actual_section: list[list]) -> str:
    """仅实际明细的 CSV——最纯净的可求和版本。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ACTUAL_HEADER)
    w.writerows(actual_section)
    return "\ufeff" + buf.getvalue()


def export_xlsx(actual_section: list[list],
                template_section: list[list] | None = None,
                daily_summary: list[list] | None = None,
                range_stats: list[list] | None = None) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "实际明细"
    ws.append(ACTUAL_HEADER)
    for r in actual_section:
        ws.append(r)

    ws2 = wb.create_sheet("模板对照")
    ws2.append(TEMPLATE_HEADER)
    for r in (template_section or []):
        ws2.append(r)

    ws3 = wb.create_sheet("日汇总")
    ws3.append(DAILY_HEADER)
    for r in (daily_summary or []):
        ws3.append(r)

    ws4 = wb.create_sheet("区间统计")
    ws4.append(["metric", "value"])
    for r in (range_stats or []):
        ws4.append(r)

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
