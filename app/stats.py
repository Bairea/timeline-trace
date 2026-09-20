"""统计聚合。设计文档 §5.4/§8.3。

只消费 compare_day 的输出，不重新计算重叠——避免统计口径与页面
显示两套算法不一致。

优先级四项的判定依赖实际块的分类，而 `actual_blocks` 没有
category 列，分类由 `app/classify.py` 从模板派生。判定所需的
名字→分类映射以 `categories` 参数传入（键为实际块 id）。

阈值来自 `config/thresholds.yaml`（经 app.config 校验），
此前是硬编码常量。不传则用默认值，保持纯函数可独立测试。
"""
from collections import Counter
from typing import Iterable, Optional

from app.classify import UNCATEGORIZED, category_of
from app.config import Thresholds

# 默认阈值。与 config/thresholds.yaml 的出厂值一致（design §5.4），
# 仅作为未传配置时的兜底，正常路径由 reports 层注入已校验的配置。
_DEFAULT = Thresholds(
    sleep_min_hours=7.0,
    sleep_target_start="22:40",
    exercise_min_minutes=5,
    exercise_max_minutes=20,
    project_min_minutes=45,
    project_max_minutes=90,
)

# 兼容旧引用。新代码请用 Thresholds，不要再从这里取常量。
SLEEP_MIN_HOURS = _DEFAULT.sleep_min_hours
PROJECT_MIN_LO, PROJECT_MIN_HI = _DEFAULT.project_min_minutes, _DEFAULT.project_max_minutes
EXERCISE_MIN_LO, EXERCISE_MIN_HI = _DEFAULT.exercise_min_minutes, _DEFAULT.exercise_max_minutes


def _dur(row: dict) -> Optional[int]:
    """块时长。未闭合（end_min 为空）返回 None，不参与统计。"""
    if row.get("end_min") is None:
        return None
    return row["end_min"] - row["start_min"]


def daily_summary(date: str, comparisons: Iterable,
                  actual_rows: list[dict] | None = None) -> list:
    """单日汇总：[date, recorded_min, unplanned_min, aligned, offset, unrecorded, unplanned]"""
    statuses = Counter()
    unplanned_min = 0
    for c in comparisons:
        statuses[c.status] += 1
        if c.status == "unplanned" and c.actual_start is not None and c.actual_end is not None:
            unplanned_min += c.actual_end - c.actual_start

    recorded = 0
    for r in (actual_rows or []):
        d = _dur(r)
        if d is not None:
            recorded += d

    return [date, recorded, unplanned_min,
            statuses["aligned"], statuses["offset"],
            statuses["unrecorded"], statuses["unplanned"]]


def _project_minutes(actuals: list[dict],
                     categories: Optional[dict[int, str]]) -> int:
    """当日「项目推进」实际块总时长。"""
    total = 0
    for r in actuals:
        if category_of(r, categories) != "项目推进":
            continue
        d = _dur(r)
        if d is not None:
            total += d
    return total


def range_stats(days: list[dict],
                thresholds: Optional[Thresholds] = None,
                categories: Optional[dict] = None) -> list[list]:
    """区间聚合。days 每项含 date / rows / actual_rows。

    `categories` 支持两种形态：
      - dict[int, str]：全局的「实际块 id → category」，跨天一次性传入；
      - dict[str, dict[int, str]]：按日期分桶。
    为空的日期桶会退回「按名字反查模板」，因此不传也能跑（只是口径更弱）。

    输出 [[metric, value], ...]，直接喂给 XLSX 的「区间统计」sheet。
    """
    t = thresholds or _DEFAULT
    if not days:
        return [["days", 0]]

    n = len(days)
    sleep_hit = 0
    exercise_hit = 0
    low_stimulus_hit = 0
    project_min_total = 0
    unplanned_min_total = 0
    project_in_range_days = 0

    for d in days:
        rows = d.get("rows", [])
        actuals = d.get("actual_rows", [])
        cats = _categories_for(d.get("date"), categories)

        # 睡眠：当日任意一个睡眠块达到下限即算达标（不看名字）。
        # 判定用 category 而非块名，因为块名用户随时可改。
        for r in actuals:
            if category_of(r, cats) != "睡眠":
                continue
            dur = _dur(r)
            if dur is not None and dur >= t.sleep_min_hours * 60:
                sleep_hit += 1
                break

        # 运动：存在一个「身体锚点」且时长落在区间内的块。
        # 下限 5 分钟排除「意思一下」，上限 20 分钟排除把别的事也标成锚点。
        for r in actuals:
            if category_of(r, cats) != "身体锚点":
                continue
            dur = _dur(r)
            if dur is not None and t.exercise_min_minutes <= dur <= t.exercise_max_minutes:
                exercise_hit += 1
                break

        if any(r.get("is_low_stimulus") for r in actuals):
            low_stimulus_hit += 1

        day_project = _project_minutes(actuals, cats)
        project_min_total += day_project
        if t.project_min_minutes <= day_project <= t.project_max_minutes:
            project_in_range_days += 1

        # 计划外时长：对照结果里 status 为 unplanned 的实际块
        unplanned_min_total += sum(
            (c.actual_end - c.actual_start)
            for c in rows
            if c.status == "unplanned"
            and c.actual_start is not None and c.actual_end is not None
        )

    return [
        ["days", n],
        ["sleep_hit_days", sleep_hit],
        ["sleep_hit_rate", round(sleep_hit / n, 3)],
        ["exercise_hit_days", exercise_hit],
        ["exercise_hit_rate", round(exercise_hit / n, 3)],
        ["low_stimulus_days", low_stimulus_hit],
        ["low_stimulus_rate", round(low_stimulus_hit / n, 3)],
        ["project_min_total", project_min_total],
        ["project_min_avg", round(project_min_total / n, 1)],
        ["unplanned_min_total", unplanned_min_total],
        ["project_in_range_days", project_in_range_days],
    ]


def _categories_for(day: str, categories: Optional[dict]) -> Optional[dict]:
    """取某日的 id→category 映射。兼容全局扁平字典与按日分桶两种形态。"""
    if not categories:
        return None
    if day in categories and isinstance(categories[day], dict):
        return categories[day]
    return categories


__all__ = [
    "daily_summary", "range_stats", "UNCATEGORIZED",
    "SLEEP_MIN_HOURS", "PROJECT_MIN_LO", "PROJECT_MIN_HI",
    "EXERCISE_MIN_LO", "EXERCISE_MIN_HI",
]
