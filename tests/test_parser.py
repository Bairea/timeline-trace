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
