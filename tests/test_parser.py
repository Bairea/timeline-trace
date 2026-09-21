import pytest
from app.parser import parse_line, ParseError


def test_full_range():
    r = parse_line("20:30-21:10 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min, r.name) == (1230, 1270, "干活")


def test_start_only_uses_prev_end():
    r = parse_line("12:45 工作", prev_end=750, now_min=0)
    assert (r.start_min, r.end_min) == (765, 795)   # 12:45 + 默认30分钟


def test_start_only_without_prev_uses_now():
    r = parse_line("12:45 工作", prev_end=None, now_min=760)
    assert (r.start_min, r.end_min) == (765, 795)


def test_open_range():
    r = parse_line("20:30- 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (1230, None)


def test_dot_and_fullwidth_colon():
    r = parse_line("20.30-21.10 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (1230, 1270)


def test_fullwidth_separator_and_colon():
    r = parse_line("２０：３０－２１：１０ 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (1230, 1270)


def test_compact_hhmm():
    r = parse_line("2030-2110 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (1230, 1270)


def test_no_name_uses_fallback():
    r = parse_line("20:30-21:10", prev_end=None, now_min=0, fallback_name="未命名")
    assert r.name == "未命名"


def test_unparseable_raises_with_raw_text():
    with pytest.raises(ParseError) as e:
        parse_line("这不是时间", prev_end=None, now_min=0)
    assert "这不是时间" in str(e.value)


def test_end_before_start_treated_as_cross_midnight():
    r = parse_line("22:40-06:30 睡觉", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (1360, 1830)


def test_span_over_16h_raises():
    with pytest.raises(ParseError):
        parse_line("01:00-20:00 异常", prev_end=None, now_min=0)


# --- 分隔符缺失时 end 组不得被吞（原缺陷：'08:30 20:30-21:30' → 12 小时） ---

def test_space_only_start_is_not_an_end():
    """只有空格时，第二个时刻是名字的一部分，不是终点。

    原缺陷：`end` 组不要求分隔符，`08:30 20:30-21:30` 被解析成
    start=08:30 end=20:30 span=720 分钟，且名字变成 '-21:30'。
    """
    r = parse_line("08:30 20:30-21:30", prev_end=None, now_min=0)
    assert r.start_min == 510
    assert r.end_min == 510 + 30, "应走「只有起点」分支，不是 12 小时跨度"
    assert r.name == "20:30-21:30", "第二个时刻应完整留在名字里"


def test_space_only_start_with_name_keeps_full_name():
    r = parse_line("08:30 20:30-21:30 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (510, 540)
    assert r.name == "20:30-21:30 干活", "名字不能被 '-21:30' 之类残片污染"


def test_space_separated_range_still_works():
    """分隔符是纯空格时，两个时刻构成区间——这是既有能力，不能修坏。"""
    r = parse_line("08:30 09:30", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (510, 570)


def test_space_separated_range_with_name():
    r = parse_line("08:30 09:30 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min, r.name) == (510, 570, "干活")


def test_name_starting_with_time_is_not_an_end():
    """名字本身以时刻开头时，前面没有分隔符，不该被当成终点。

    `12:00 20:30-21:30 复盘` 里的 「20:30-21:30」是名字。
    """
    r = parse_line("12:00 20:30-21:30 复盘", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (720, 750)
    assert r.name == "20:30-21:30 复盘"


def test_hyphen_separator_still_works():
    r = parse_line("08:30-09:30 干活", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min, r.name) == (510, 570, "干活")


def test_multi_space_still_allows_range():
    r = parse_line("08:30   09:30", prev_end=None, now_min=0)
    assert (r.start_min, r.end_min) == (510, 570)
