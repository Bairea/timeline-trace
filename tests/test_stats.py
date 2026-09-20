"""统计聚合测试。设计文档 §5.4。

优先级四项的判定依赖实际块的 category，而实际块没有这一列，
由 app/classify.py 从模板派生。故这里分两层测：

  1. 分类推断（classify）：名字与时间如何映射到 category；
  2. 聚合口径（range_stats）：拿到 category 后如何算达标。

不传 categories 时聚合退回「其他」，达标项一律为 0——这是有意的：
宁可统计不出来，也不要靠块名瞎猜。
"""
from app.classify import UNCATEGORIZED, infer_category, infer_category_map
from app.compare import BlockLike, compare_day
from app.config import Thresholds
from app.stats import daily_summary, range_stats


def _actual(start, end, name, low=False, bid=None):
    r = {"start_min": start, "end_min": end, "name": name,
         "is_low_stimulus": low}
    if bid is not None:
        r["id"] = bid
    return r


# 一份与 config/timeline.yaml 同构的精简模板，供分类测试使用。
TPL = [
    {"id": 1, "start_min": 390, "end_min": 420, "name": "早操", "category": "身体锚点"},
    {"id": 2, "start_min": 440, "end_min": 450, "name": "早饭", "category": "事务"},
    {"id": 3, "start_min": 510, "end_min": 720, "name": "工作", "category": "项目推进"},
    {"id": 4, "start_min": 1230, "end_min": 1320, "name": "干活（中间做拉伸）", "category": "项目推进"},
    {"id": 5, "start_min": 1360, "end_min": 1830, "name": "睡觉", "category": "睡眠"},
]


def _cats(pairs):
    """按 (id, category) 构造映射。"""
    return dict(pairs)


# ---------- 分类推断 ----------

def test_infer_by_exact_name():
    r = _actual(510, 740, "工作")
    assert infer_category(r, TPL) == "项目推进"


def test_infer_by_name_containing_template_name():
    """实际块名「干活」应匹配模板名「干活（中间做拉伸）」。"""
    r = _actual(1230, 1270, "干活")
    assert infer_category(r, TPL) == "项目推进"


def test_infer_by_time_when_name_is_useless():
    """名字没线索时按时间兜底：块基本填满模板块时段。"""
    r = _actual(510, 700, "忙别的")      # 占 510-720 的 190/210
    assert infer_category(r, TPL) == "项目推进"


def test_unrelated_block_inside_template_span_is_not_absorbed():
    """模板块内做的别的事不得继承其 category。

    这是最容易让「项目推进」虚高的场景：干活时段里刷视频。
    """
    r = _actual(1270, 1300, "短视频")    # 落在 1230-1320 内，但只占 33%
    assert infer_category(r, TPL) == UNCATEGORIZED


def test_infer_returns_uncategorized_without_template():
    assert infer_category(_actual(510, 740, "工作"), []) == UNCATEGORIZED


def test_infer_skips_open_ended_block():
    r = {"start_min": 1230, "end_min": None, "name": "干活"}
    assert infer_category(r, TPL) == UNCATEGORIZED


def test_name_match_ignores_time_on_purpose():
    """名字匹配刻意不看时间——这是有意决定，不是疏漏。

    名字不是「匹配模板块」的线索，而是用户对「这是什么事」的直接声明。
    用户打了「干活」，就是说他处于干活状态，时间放在上午还是晚上不影响
    分类。若要求时间重叠，就会丢掉「785–845 干活」这种记录（模板里
    上午叫「工作」、干活排在 20:30）——而时间错位恰恰是这个工具最该
    暴露的东西，统计层不该把它悄悄丢掉。

    这条测试守着上面这个结论，防止后人「顺手修正」成带时间约束的版本。
    """
    tpl = [
        {"id": 1, "start_min": 510, "end_min": 720, "name": "工作",
         "category": "项目推进"},
        {"id": 2, "start_min": 1230, "end_min": 1320,
         "name": "干活（中间做拉伸）", "category": "项目推进"},
    ]
    # 12:45–14:05 记「干活」：名字匹配规则②，但时间与「干活」模板块无交集
    r = _actual(785, 845, "干活")
    assert infer_category(r, tpl) == "项目推进"


def test_empty_name_falls_back_to_time():
    """没有名字线索时才启用时间兜底。"""
    tpl = [{"id": 1, "start_min": 510, "end_min": 720, "name": "工作",
            "category": "项目推进"}]
    assert infer_category(_actual(510, 700, "未命名"), tpl) == "项目推进"


def test_unknown_name_short_record_falls_through():
    """已知局限：名字无关联 + 记录远短于模板块 → 落榜。

    见 docs/reviews/2026-09-20-template-config-review.md §4。
    这条测试固定住当前行为，等语义决策定了再改。
    """
    tpl = [{"id": 1, "start_min": 510, "end_min": 720, "name": "工作",
            "category": "项目推进"}]
    assert infer_category(_actual(510, 540, "专注写代码"), tpl) == UNCATEGORIZED


def test_infer_category_map_keys_by_id():
    """同名块在同一天可能有两个，映射必须以 id 为键。"""
    rows = [_actual(390, 400, "早操", bid=7), _actual(1340, 1355, "晚练", bid=8)]
    m = infer_category_map(rows, TPL)
    assert m == {7: "身体锚点", 8: UNCATEGORIZED}


# ---------- 日汇总 ----------

def test_daily_summary_counts_statuses():
    tpls = [BlockLike(390, 420, "早操"), BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(395, 422, "早操")]
    rows = compare_day(tpls, acts)
    s = daily_summary("2026-09-20", rows, [_actual(395, 422, "早操")])
    assert s[0] == "2026-09-20"
    assert s[1] == 27            # recorded_min
    assert s[3] == 1             # aligned
    assert s[5] == 1             # unrecorded（干活）


def test_daily_summary_ignores_open_ended_blocks():
    """未闭合块（end_min 为 None）不计入已记录时长。"""
    rows = []
    s = daily_summary("2026-09-20", rows,
                      [{"start_min": 1230, "end_min": None, "name": "干活"}])
    assert s[1] == 0


def test_daily_summary_unplanned_minutes():
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(100, 130, "夜里刷剧")]
    rows = compare_day(tpls, acts)
    s = daily_summary("2026-09-20", rows, [_actual(100, 130, "夜里刷剧")])
    assert s[2] == 30            # unplanned_min


# ---------- 区间聚合 ----------

def test_range_stats_empty():
    assert range_stats([])[0] == ["days", 0]


def test_range_stats_sleep_hit():
    rows = [_actual(1360, 1830, "睡觉", bid=1)]
    days = [{"date": "d1", "rows": [], "actual_rows": rows}]
    st = dict(range_stats(days, categories={"d1": {1: "睡眠"}}))
    assert st["days"] == 1
    assert st["sleep_hit_days"] == 1
    assert st["sleep_hit_rate"] == 1.0


def test_range_stats_sleep_miss_below_7h():
    rows = [_actual(1400, 1750, "睡觉", bid=1)]      # 350 分钟 < 7h
    days = [{"date": "d1", "rows": [], "actual_rows": rows}]
    st = dict(range_stats(days, categories={"d1": {1: "睡眠"}}))
    assert st["sleep_hit_days"] == 0


def test_range_stats_sleep_ignores_name():
    """睡眠达标只看 category，块名叫什么都行。"""
    rows = [_actual(1360, 1830, "随便叫个名字", bid=1)]
    days = [{"date": "d1", "rows": [], "actual_rows": rows}]
    st = dict(range_stats(days, categories={"d1": {1: "睡眠"}}))
    assert st["sleep_hit_days"] == 1


def test_range_stats_exercise_window():
    """5-20 分钟的锚点块算达标，超出区间不算。"""
    days = [
        {"date": "d1", "rows": [], "actual_rows": [_actual(390, 420, "早操", bid=1)]},  # 30min
        {"date": "d2", "rows": [], "actual_rows": [_actual(390, 400, "早操", bid=2)]},  # 10min
    ]
    cats = {"d1": {1: "身体锚点"}, "d2": {2: "身体锚点"}}
    st = dict(range_stats(days, categories=cats))
    assert st["exercise_hit_days"] == 1


def test_range_stats_exercise_ignores_name():
    """名字不含「操」「练」也能达标——旧口径做不到这点。"""
    days = [{"date": "d1", "rows": [],
             "actual_rows": [_actual(390, 400, "拉伸一下", bid=1)]}]
    st = dict(range_stats(days, categories={"d1": {1: "身体锚点"}}))
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
        {"date": "d1", "rows": [], "actual_rows": [_actual(1230, 1290, "干活", bid=1)]},  # 60
        {"date": "d2", "rows": [], "actual_rows": [_actual(1230, 1320, "干活", bid=2)]},  # 90
    ]
    st = dict(range_stats(days, categories={"d1": {1: "项目推进"},
                                            "d2": {2: "项目推进"}}))
    assert st["project_min_total"] == 150
    assert st["project_min_avg"] == 75.0
    assert st["project_in_range_days"] == 2


def test_range_stats_project_excludes_uncategorized():
    rows = [
        _actual(1230, 1290, "干活", bid=1),
        _actual(1290, 1320, "短视频", bid=2),
    ]
    days = [{"date": "d1", "rows": [], "actual_rows": rows}]
    st = dict(range_stats(days, categories={"d1": {1: "项目推进", 2: UNCATEGORIZED}}))
    assert st["project_min_total"] == 60


def test_range_stats_project_in_range_days():
    """落在 45-90 区间内才算「达标日」。"""
    days = [
        {"date": "d1", "rows": [], "actual_rows": [_actual(1230, 1275, "干活", bid=1)]},  # 45 ✓
        {"date": "d2", "rows": [], "actual_rows": [_actual(1230, 1290, "干活", bid=2)]},  # 60 ✓
        {"date": "d3", "rows": [], "actual_rows": [_actual(1230, 1320, "干活", bid=3)]},  # 90 ✓
        {"date": "d4", "rows": [], "actual_rows": [_actual(1230, 1235, "干活", bid=4)]},  # 5 ✗
    ]
    cats = {f"d{i}": {i: "项目推进"} for i in (1, 2, 3, 4)}
    st = dict(range_stats(days, categories=cats))
    assert st["project_min_total"] == 200
    assert st["project_in_range_days"] == 3


def test_range_stats_custom_thresholds():
    """阈值可由配置注入——不改代码就能调口径。"""
    days = [{"date": "d1", "rows": [],
             "actual_rows": [_actual(1360, 1750, "睡觉", bid=1)]}]   # 390min = 6.5h
    custom = Thresholds(sleep_min_hours=6.0, sleep_target_start="22:40",
                        exercise_min_minutes=5, exercise_max_minutes=20,
                        project_min_minutes=45, project_max_minutes=90)
    st = dict(range_stats(days, custom, {"d1": {1: "睡眠"}}))
    assert st["sleep_hit_days"] == 1        # 6.5h >= 6h


def test_range_stats_accepts_flat_category_map():
    """categories 也接受不分日的扁平字典。"""
    rows = [_actual(1230, 1290, "干活", bid=1)]
    days = [{"date": "d1", "rows": [], "actual_rows": rows}]
    st = dict(range_stats(days, categories={1: "项目推进"}))
    assert st["project_min_total"] == 60


def test_range_stats_without_categories_yields_zero():
    """不传分类映射时不应靠名字猜——宁可统计不出来。"""
    days = [{"date": "d1", "rows": [],
             "actual_rows": [_actual(1360, 1830, "睡觉", bid=1)]}]
    st = dict(range_stats(days))
    assert st["sleep_hit_days"] == 0
    assert st["project_min_total"] == 0


def test_range_stats_unplanned_minutes():
    tpls = [BlockLike(1230, 1320, "干活")]
    rows = compare_day(tpls, [BlockLike(100, 130, "夜里刷剧")])
    days = [{"date": "d1", "rows": rows, "actual_rows": [_actual(100, 130, "夜里刷剧")]}]
    st = dict(range_stats(days))
    assert st["unplanned_min_total"] == 30
