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


# ---------- 最小重叠阈值：边界伪影 ----------

def test_tiny_boundary_overlap_is_unrecorded():
    """2 分钟边界相接是生活常态，不是偏移。设计文档 §5.1 补充规则。

    早操 06:35-07:02 与模板「洗漱」07:00-07:15 只重叠 2 分钟，
    不应被判为 offset（否则日报会被伪影淹没）。
    """
    tpl = BlockLike(420, 435, "洗漱")          # 07:00-07:15
    act = BlockLike(395, 422, "早操")          # 06:35-07:02，重叠 2 分钟
    r = compare_block(tpl, [act])
    assert r.status == "unrecorded"
    assert r.actual_name is None


def test_overlap_at_threshold_counts():
    """恰好达到阈值（5 分钟）应算 offset。"""
    tpl = BlockLike(420, 435, "洗漱")
    act = BlockLike(400, 425, "某活动")        # 重叠 5 分钟
    r = compare_block(tpl, [act])
    assert r.status == "offset"


def test_overlap_just_below_threshold_is_unrecorded():
    tpl = BlockLike(420, 435, "洗漱")
    act = BlockLike(400, 424, "某活动")        # 重叠 4 分钟
    r = compare_block(tpl, [act])
    assert r.status == "unrecorded"


def test_tiny_overlap_does_not_hide_real_match():
    """阈值不能把真正的命中吃掉：同模板块有真命中和伪影时应取真命中。"""
    tpl = BlockLike(420, 435, "洗漱")
    ghost = BlockLike(395, 422, "早操")        # 伪影，重叠 2 分钟
    real = BlockLike(422, 437, "洗漱")         # 真命中
    r = compare_block(tpl, [ghost, real])
    assert r.status == "aligned"
    assert r.actual_name == "洗漱"


def test_tiny_overlap_block_still_appears_in_day_output():
    """阈值只影响判定，不能让实际块从输出中消失。"""
    tpls = [BlockLike(420, 435, "洗漱")]
    acts = [BlockLike(395, 422, "早操")]
    results = compare_day(tpls, acts)
    names = [r.actual_name for r in results if r.actual_name]
    assert "早操" in names


# ---------- 短模板块：纯绝对阈值会误伤 ----------

def test_short_block_shifted_by_1min_is_not_lost():
    """模板里「出门前准备」只有 5 分钟（07:30-07:35）。

    纯绝对阈值 5 会让它挪 1 分钟就变 unrecorded——即用户明明做了，
    系统却说没做。覆盖率兜底必须生效。
    """
    tpl = BlockLike(450, 455, "出门前准备")     # 5 分钟
    act = BlockLike(451, 456, "出门前准备")     # 挪 1 分钟，重叠 4 分钟
    r = compare_block(tpl, [act])
    assert r.status != "unrecorded", "短块轻微偏移不应被判为未记录"
    assert r.actual_name == "出门前准备"


def test_short_block_low_coverage_still_unrecorded():
    """覆盖率不足的短块仍应忽略——阈值不能形同虚设。"""
    tpl = BlockLike(450, 455, "出门前准备")
    act = BlockLike(454, 460, "别的事")         # 重叠仅 1 分钟 = 20%
    r = compare_block(tpl, [act])
    assert r.status == "unrecorded"


def test_short_block_exact_match_aligned():
    tpl = BlockLike(450, 455, "出门前准备")
    act = BlockLike(450, 455, "出门前准备")
    r = compare_block(tpl, [act])
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
