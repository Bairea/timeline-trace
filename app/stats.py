"""统计聚合。设计文档 §5.4/§8.3。

只消费 compare_day 的输出，不重新计算重叠——避免统计口径与页面
显示两套算法不一致。
"""
from collections import Counter
from typing import Iterable

SLEEP_MIN_HOURS = 7.0
PROJECT_MIN_LO, PROJECT_MIN_HI = 45, 90
EXERCISE_MIN_LO, EXERCISE_MIN_HI = 5, 20


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
        if r.get("end_min") is not None:
            recorded += r["end_min"] - r["start_min"]

    return [date, recorded, unplanned_min,
            statuses["aligned"], statuses["offset"],
            statuses["unrecorded"], statuses["unplanned"]]


def range_stats(days: list[dict]) -> list[list]:
    """区间聚合。days 每项含 date / rows / actual_rows。

    输出 [[metric, value], ...]，直接喂给 XLSX 的「区间统计」sheet。
    """
    if not days:
        return [["days", 0]]

    n = len(days)
    sleep_hit = 0
    exercise_hit = 0
    low_stimulus_hit = 0
    project_min_total = 0
    unplanned_min_total = 0

    for d in days:
        rows = d.get("rows", [])
        actuals = d.get("actual_rows", [])

        sleep = [r for r in actuals if r["name"] == "睡觉" and r["end_min"] is not None]
        for s in sleep:
            if (s["end_min"] - s["start_min"]) >= SLEEP_MIN_HOURS * 60:
                sleep_hit += 1
                break

        ex = [r for r in actuals
              if r["end_min"] is not None
              and EXERCISE_MIN_LO <= (r["end_min"] - r["start_min"]) <= EXERCISE_MIN_HI
              and ("操" in r["name"] or "练" in r["name"])]
        if ex:
            exercise_hit += 1

        if any(r.get("is_low_stimulus") for r in actuals):
            low_stimulus_hit += 1

        project_min_total += sum(
            r["end_min"] - r["start_min"]
            for r in actuals
            if r["end_min"] is not None and "干活" in r["name"]
        )

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
        ["project_in_range_days",
         sum(1 for d in days
             if PROJECT_MIN_LO <= sum(
                 r["end_min"] - r["start_min"] for r in d.get("actual_rows", [])
                 if r["end_min"] is not None and "干活" in r["name"]) <= PROJECT_MIN_HI)],
    ]
