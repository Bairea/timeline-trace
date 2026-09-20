from app.compare import BlockLike, compare_block, compare_day, overlap_minutes


# ---------- overlap_minutes ----------

def test_overlap_full_containment():
    assert overlap_minutes(600, 660, 580, 700) == 60


def test_overlap_no_intersection():
    assert overlap_minutes(600, 660, 700, 760) == 0


def test_overlap_partial():
    assert overlap_minutes(600, 660, 640, 700) == 20


def test_overlap_touching_edges_is_zero():
    assert overlap_minutes(600, 660, 660, 700) == 0


def test_overlap_cross_midnight_block():
    # 22:40-次日06:30 = 1360..1830，与 06:00-07:00 = 360..420 无交集
    assert overlap_minutes(1360, 1830, 360, 420) == 0


# ---------- compare_block ----------

def test_aligned_when_within_tolerance():
    tpl = BlockLike(390, 420, "早操")          # 06:30-07:00
    act = BlockLike(395, 422, "早操")          # 06:35-07:02，起点偏 5，时长偏 -3
    r = compare_block(tpl, [act])
    assert r.status == "aligned"
    assert r.delta_start_min == 5
    assert r.delta_dur_min == -3


def test_offset_when_start_beyond_tolerance():
    tpl = BlockLike(720, 765, "午饭与午休")     # 12:00-12:45
    act = BlockLike(740, 785, "午饭与午休")     # 12:20-13:05，起点偏 20 > 15
    r = compare_block(tpl, [act])
    assert r.status == "offset"
    assert r.delta_start_min == 20


def test_offset_when_duration_short():
    tpl = BlockLike(1230, 1320, "干活")        # 20:30-22:00
    act = BlockLike(1230, 1270, "干活")        # 20:30-21:10，仅 40 分钟
    r = compare_block(tpl, [act])
    assert r.status == "offset"
    assert r.delta_dur_min == -50


def test_unrecorded_when_no_actual_overlap():
    tpl = BlockLike(1320, 1340, "晚练")        # 22:20-22:40
    r = compare_block(tpl, [])
    assert r.status == "unrecorded"
    assert r.actual_name is None


def test_no_overlap_at_all_is_unrecorded():
    tpl = BlockLike(1320, 1340, "晚练")
    act = BlockLike(600, 700, "工作")
    r = compare_block(tpl, [act])
    assert r.status == "unrecorded"


def test_aligned_takes_best_when_multiple_actuals():
    """一个模板块对应多个实际块时，status 取最优的一档。"""
    tpl = BlockLike(1230, 1320, "干活")
    a_short = BlockLike(1230, 1270, "干活")    # offset
    a_good = BlockLike(1235, 1315, "干活")     # aligned
    r = compare_block(tpl, [a_short, a_good])
    assert r.status == "aligned"


# ---------- compare_day ----------

def test_compare_day_marks_unplanned():
    """计划外 = 该实际块与所有模板块重叠均为 0（设计文档 §5.1）。

    模板块仅 20:30-22:00（干活）。06:00-06:15 的「刷手机」落在所有
    模板窗口之外，故为 unplanned。
    """
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(360, 375, "刷手机")]
    results = compare_day(tpls, acts)
    unplanned = [r for r in results if r.status == "unplanned"]
    assert len(unplanned) == 1
    assert unplanned[0].actual_name == "刷手机"
    assert unplanned[0].template_name is None


def test_compare_day_activity_inside_template_window_is_offset_not_unplanned():
    """落在模板窗口内的其他活动是 offset（换了做的事），不是 unplanned。"""
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(1230, 1270, "干活"), BlockLike(1270, 1290, "短视频")]
    results = compare_day(tpls, acts)
    assert [r for r in results if r.status == "unplanned"] == []
    # 「干活」命中模板；「短视频」与模板有 20 分钟交集 → offset
    assert len(results) == 2


def test_compare_day_returns_one_row_per_actual_plus_unrecorded_templates():
    tpls = [BlockLike(390, 420, "早操"), BlockLike(1320, 1340, "晚练")]
    acts = [BlockLike(395, 422, "早操"), BlockLike(100, 120, "夜里刷剧")]
    results = compare_day(tpls, acts)
    # 早操 → aligned；晚练 → unrecorded；夜里刷剧 → unplanned
    assert len(results) == 3
    statuses = sorted(r.status for r in results)
    assert statuses == ["aligned", "unplanned", "unrecorded"]


# ---------- 不变式：实际块绝不静默丢失 ----------

def test_every_actual_block_appears_in_output():
    """核心不变式。一个工具如果会吞掉用户记的东西就彻底失去信任。"""
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [
        BlockLike(1230, 1270, "干活"),
        BlockLike(1270, 1290, "短视频"),
        BlockLike(360, 375, "刷手机"),
    ]
    results = compare_day(tpls, acts)
    out = {(r.actual_start, r.actual_end) for r in results if r.actual_start is not None}
    for a in acts:
        assert (a.start_min, a.end_min) in out, f"实际块被丢弃: {a}"


def test_lossy_case_two_actuals_one_template_slot():
    """两个实际块争一个模板槽位时，落败的那个也必须出现（归 offset）。"""
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(1230, 1270, "干活"), BlockLike(1270, 1290, "短视频")]
    results = compare_day(tpls, acts)
    assert len(results) == 2
    names = sorted(r.actual_name for r in results)
    assert names == ["干活", "短视频"]
