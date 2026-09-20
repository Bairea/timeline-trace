"""配置加载测试。设计文档 §2.3 / §5.4。

配置文件化最容易做砸的地方是**报错质量**：写错一个字段名，
如果只抛 KeyError 或者「配置不合法」，用户得靠猜。故这里大量断言
错误消息里的定位信息（第几个模板、第几个块、哪个字段）。

解析函数是纯函数（吃 dict），所以测试不需要造 YAML 文件。
"""
import pytest
import yaml

from app.config import (CANDIDATE_CATEGORIES, ConfigError, load_thresholds,
                        load_timeline, parse_thresholds, parse_timeline,
                        to_minutes)


# ---------- 时间解析 ----------

@pytest.mark.parametrize("raw,expected", [
    ("06:30", 390),
    ("00:00", 0),
    ("24:00", 1440),
    ("22:40", 1360),
    ("7:5", 425),
    # 纯数字字符串按时刻解析，与 app/parser.py 手感一致
    ("0830", 510),
    ("830", 510),
    # 不带引号的整数才是分钟数
    (390, 390),
    (0, 0),
    (1440, 1440),
])
def test_to_minutes_accepts(raw, expected):
    assert to_minutes(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "abc", "6:60", "25:00", "25:01", -1, 1441, None, 3.5, True,
    "390",           # 纯数字字符串是时刻(3:90)不合法，分钟数要写不带引号的 390
    "12345",         # 5 位数字无法解读为时刻
])
def test_to_minutes_rejects(raw):
    with pytest.raises(ConfigError):
        to_minutes(raw)


def test_to_minutes_error_message_contains_value():
    """报错必须带上出错的值，否则用户不知道改哪一行。"""
    with pytest.raises(ConfigError) as e:
        to_minutes("6:60")
    assert "6:60" in str(e.value)


# ---------- 时间线解析 ----------

def _block(start="06:30", end="07:00", name="早操", **kw):
    d = {"start": start, "end": end, "name": name}
    d.update(kw)
    return d


def _timeline(blocks=None, **tpl_kw):
    t = {"name": "工作日", "is_default": True,
         "blocks": blocks or [_block()]}
    t.update(tpl_kw)
    return {"templates": [t]}


def test_parse_minimal_timeline():
    specs = parse_timeline(_timeline())
    assert len(specs) == 1
    assert specs[0].name == "工作日"
    assert specs[0].is_default is True
    assert specs[0].blocks[0].start_min == 390


def test_parse_assigns_sort_order_by_file_position():
    """文件顺序即显示顺序，不要求手写 sort_order。"""
    specs = parse_timeline(_timeline([
        _block("06:30", "07:00", "A"),
        _block("07:00", "08:00", "B"),
        _block("08:00", "09:00", "C"),
    ]))
    assert [b.sort_order for b in specs[0].blocks] == [0, 1, 2]


def test_parse_normalizes_midnight_crossing():
    """end 早于 start 表示跨零点，自动补一天。"""
    specs = parse_timeline(_timeline([_block("22:40", "06:30", "睡觉")]))
    b = specs[0].blocks[0]
    assert (b.start_min, b.end_min) == (1360, 1830)


def test_parse_rejects_missing_name():
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline([{"start": "06:30", "end": "07:00"}]))
    assert "name" in str(e.value)


def test_parse_rejects_empty_name():
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline([_block(name="   ")]))
    assert "name" in str(e.value)


def test_parse_rejects_bad_time_with_location():
    """错误消息须指出是第几个块。"""
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline([_block(), _block(start="99:99")]))
    msg = str(e.value)
    assert "blocks[1]" in msg
    assert "99:99" in msg


def test_parse_rejects_unknown_category_with_candidates():
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline([_block(category="睡觉")]))
    msg = str(e.value)
    assert "睡觉" in msg
    assert "睡眠" in msg          # 候选值须列出，否则用户不知道正确写法


@pytest.mark.parametrize("cat", CANDIDATE_CATEGORIES)
def test_parse_accepts_all_candidate_categories(cat):
    specs = parse_timeline(_timeline([_block(category=cat)]))
    assert specs[0].blocks[0].category == cat


def test_parse_allows_category_omitted():
    specs = parse_timeline(_timeline([_block()]))
    assert specs[0].blocks[0].category is None


def test_parse_rejects_out_of_order_blocks():
    """块时间反序几乎一定是手编文件时写颠倒了。"""
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline([
            _block("08:00", "09:00", "晚的"),
            _block("06:00", "07:00", "早的"),
        ]))
    assert "顺序" in str(e.value) or "早于" in str(e.value)


def test_parse_allows_gaps_between_blocks():
    """块之间允许留空隙——真实生活本来就有。"""
    specs = parse_timeline(_timeline([
        _block("06:30", "07:00", "A"),
        _block("09:00", "10:00", "B"),      # 中间空 2 小时
    ]))
    assert len(specs[0].blocks) == 2


def test_parse_requires_default_template():
    """没有默认模板 → 对照页会 404，加载时就该拦下。"""
    with pytest.raises(ConfigError) as e:
        parse_timeline(_timeline(is_default=False))
    assert "is_default" in str(e.value)


def test_parse_rejects_duplicate_template_names():
    """同名模板会让 seed 的幂等判断含混。"""
    data = {"templates": [
        {"name": "工作日", "is_default": True, "blocks": [_block()]},
        {"name": "工作日", "blocks": [_block()]},
    ]}
    with pytest.raises(ConfigError) as e:
        parse_timeline(data)
    assert "重复" in str(e.value)


def test_parse_rejects_empty_blocks():
    with pytest.raises(ConfigError):
        parse_timeline({"templates": [{"name": "x", "is_default": True, "blocks": []}]})


def test_parse_rejects_non_mapping():
    with pytest.raises(ConfigError):
        parse_timeline(["not", "a", "dict"])


def test_parse_rejects_none():
    with pytest.raises(ConfigError):
        parse_timeline(None)


def test_parse_accepts_multiple_templates():
    data = {"templates": [
        {"name": "工作日", "is_default": True, "blocks": [_block()]},
        {"name": "周末", "blocks": [_block("10:00", "11:00", "睡懒觉")]},
    ]}
    specs = parse_timeline(data)
    assert [t.name for t in specs] == ["工作日", "周末"]
    assert [t.is_default for t in specs] == [True, False]


# ---------- 阈值解析 ----------

def _thresholds(**over):
    d = {
        "sleep": {"min_hours": 7.0, "target_start": "22:40"},
        "exercise": {"min_minutes": 5, "max_minutes": 20},
        "project": {"min_minutes": 45, "max_minutes": 90},
    }
    d.update(over)
    return d


def test_parse_thresholds_ok():
    t = parse_thresholds(_thresholds())
    assert t.sleep_min_hours == 7.0
    assert t.sleep_target_start == "22:40"
    assert (t.exercise_min_minutes, t.exercise_max_minutes) == (5, 20)
    assert (t.project_min_minutes, t.project_max_minutes) == (45, 90)


@pytest.mark.parametrize("over", [
    {"sleep": {"target_start": "22:40"}},                       # 缺 min_hours
    {"exercise": {"min_minutes": 5}},                           # 缺 max
    {},                                                          # 全缺
])
def test_parse_thresholds_reports_missing_field(over):
    with pytest.raises(ConfigError) as e:
        parse_thresholds(over)
    assert "缺少" in str(e.value)


def test_parse_thresholds_rejects_inverted_range():
    with pytest.raises(ConfigError) as e:
        parse_thresholds(_thresholds(project={"min_minutes": 90, "max_minutes": 45}))
    assert "project" in str(e.value)


def test_parse_thresholds_rejects_zero_min():
    with pytest.raises(ConfigError):
        parse_thresholds(_thresholds(exercise={"min_minutes": 0, "max_minutes": 20}))


def test_parse_thresholds_rejects_bool_as_number():
    """True 是 int 的子类，容易被当成 1 混过去。"""
    with pytest.raises(ConfigError):
        parse_thresholds(_thresholds(sleep={"min_hours": True, "target_start": "22:40"}))


def test_parse_thresholds_rejects_bad_target_start():
    with pytest.raises(ConfigError) as e:
        parse_thresholds(_thresholds(sleep={"min_hours": 7.0, "target_start": "25:00"}))
    assert "target_start" in str(e.value)


def test_parse_thresholds_rejects_sleep_over_24h():
    with pytest.raises(ConfigError):
        parse_thresholds(_thresholds(sleep={"min_hours": 25, "target_start": "22:40"}))


# ---------- 读文件 ----------

def test_load_timeline_from_real_config():
    """出厂配置必须能加载——这是启动路径，坏了 app 起不来。"""
    specs = load_timeline()
    assert specs[0].name == "工作日"
    assert len(specs[0].blocks) == 18


def test_load_thresholds_from_real_config():
    t = load_thresholds()
    assert t.sleep_min_hours == 7.0
    assert (t.project_min_minutes, t.project_max_minutes) == (45, 90)


def test_load_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_timeline(tmp_path / "nope.yaml")
    assert "不存在" in str(e.value)


def test_load_reports_yaml_syntax_error(tmp_path):
    """YAML 语法错误须转成 ConfigError 并带上文件名，而不是漏出 yaml 的内部异常。"""
    p = tmp_path / "bad.yaml"
    p.write_text("templates: [\n  name: 没有闭合\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_timeline(p)
    assert "bad.yaml" in str(e.value)


def test_yaml_config_roundtrips_through_dump():
    """确保真实配置能被 yaml.safe_load 干净读回（无隐式类型陷阱）。"""
    from app.config import TIMELINE_PATH
    data = yaml.safe_load(TIMELINE_PATH.read_text(encoding="utf-8"))
    specs = parse_timeline(data)
    assert len(specs[0].blocks) == 18
