from app.compare import BlockLike, compare_day
from app.stats import daily_summary, range_stats


def _actual(start, end, name, low=False):
    return {"start_min": start, "end_min": end, "name": name,
            "is_low_stimulus": low}


def test_daily_summary_counts_statuses():
    tpls = [BlockLike(390, 420, "早操"), BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(395, 422, "早操")]
    rows = compare_day(tpls, acts)
    s = daily_summary("2026-09-20", rows, [_actual(395, 422, "早操")])
    assert s[0] == "2026-09-20"
    assert s[1] == 27            # recorded_min
    assert s[3] == 1             # aligned
    assert s[5] == 1             # unrecorded（干活）


def test_daily_summary_unplanned_minutes():
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(100, 130, "夜里刷剧")]
    rows = compare_day(tpls, acts)
    s = daily_summary("2026-09-20", rows, [_actual(100, 130, "夜里刷剧")])
    assert s[2] == 30            # unplanned_min


def test_range_stats_empty():
    assert range_stats([])[0] == ["days", 0]


def test_range_stats_sleep_hit():
    days = [{
        "date": "2026-09-20",
        "rows": [],
        "actual_rows": [_actual(1360, 1830, "睡觉")],   # 470 分钟 > 7h
    }]
    st = dict(range_stats(days))
    assert st["days"] == 1
    assert st["sleep_hit_days"] == 1
    assert st["sleep_hit_rate"] == 1.0


def test_range_stats_sleep_miss_below_7h():
    days = [{
        "date": "2026-09-20",
        "rows": [],
        "actual_rows": [_actual(1400, 1750, "睡觉")],   # 350 分钟 < 7h
    }]
    st = dict(range_stats(days))
    assert st["sleep_hit_days"] == 0


def test_range_stats_exercise_window():
    """5-20 分钟的操/练算达标，超出区间不算。"""
    days = [
        {"date": "d1", "rows": [], "actual_rows": [_actual(390, 420, "早操")]},   # 30min → 不算
        {"date": "d2", "rows": [], "actual_rows": [_actual(390, 400, "早操")]},   # 10min → 算
    ]
    st = dict(range_stats(days))
    assert st["exercise_hit_days"] == 1


def test_range_stats_low_stimulus_flag():
    days = [
        {"date": "d1", "rows": [], "actual_rows": [_actual(1215, 1230, "读书", low=True)]},
        {"date": "d2", "rows": [], "actual_rows": [_actual(1215, 1230, "读书")]},
    ]
    st = dict(range_stats(days))
    assert st["low_stimulus_days"] == 1


def test_range_stats_project_minutes_sum():
    days = [
        {"date": "d1", "rows": [], "actual_rows": [_actual(1230, 1290, "干活")]},  # 60
        {"date": "d2", "rows": [], "actual_rows": [_actual(1230, 1320, "干活")]},  # 90
    ]
    st = dict(range_stats(days))
    assert st["project_min_total"] == 150
    assert st["project_min_avg"] == 75.0
    assert st["project_in_range_days"] == 2


def test_range_stats_unplanned_minutes():
    tpls = [BlockLike(1230, 1320, "干活")]
    rows = compare_day(tpls, [BlockLike(100, 130, "夜里刷剧")])
    days = [{"date": "d1", "rows": rows, "actual_rows": [_actual(100, 130, "夜里刷剧")]}]
    st = dict(range_stats(days))
    assert st["unplanned_min_total"] == 30
