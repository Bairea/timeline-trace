"""配置加载。设计文档 §2.3 / §5.4。

配置文件只负责**初始定义**，不参与运行时读写——数据库仍是唯一真相源。
这样做的理由：对照结果本就是查询时实时计算的（design §3.1 第 4 条），
如果模板再有一个 YAML 副本，就会出现「库里改过、文件没改」的双源漂移，
而这种漂移在统计口径上会直接表现为数字对不上，极难排查。

设计取舍：
- 解析函数是**纯函数**（`parse_timeline` / `parse_thresholds` 只吃 dict），
  读文件单独一层（`load_*`）。这样测试不需要造 YAML 文件。
- 所有校验错误都带**定位信息**（第几个模板、第几个块、哪个字段），
  不能只抛 KeyError——配置文件化最常见的抱怨就是「改了没生效，
  但不知道哪一行写错了」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from app.compare import DAY_MIN

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
TIMELINE_PATH = CONFIG_DIR / "timeline.yaml"
THRESHOLDS_PATH = CONFIG_DIR / "thresholds.yaml"

# 设计文档 §3.1 第 2 条给出的候选值。不做数据库级枚举约束，
# 但配置文件里写错字要立刻报错——这是文件相对界面录入唯一的好处，不浪费。
CANDIDATE_CATEGORIES = ("睡眠", "身体锚点", "情绪稳定", "项目推进", "通勤", "事务", "其他")


class ConfigError(ValueError):
    """配置不合法。消息必须带定位信息，供用户直接去改文件。"""


@dataclass
class BlockSpec:
    """一条模板块定义。时间已归一化为分钟数。"""
    start_min: int
    end_min: int
    name: str
    category: Optional[str] = None
    sort_order: int = 0


@dataclass
class TemplateSpec:
    name: str
    description: str = ""
    is_default: bool = False
    blocks: list[BlockSpec] = field(default_factory=list)


@dataclass
class Thresholds:
    sleep_min_hours: float
    sleep_target_start: str
    exercise_min_minutes: int
    exercise_max_minutes: int
    project_min_minutes: int
    project_max_minutes: int


def to_minutes(text: Any) -> int:
    """把 "HH:MM" 或分钟整数转成自 00:00 起的分钟数。

    接受两种写法是因为手编文件时两种都自然：写时刻用 "06:30"，
    写时长区间边界用不带引号的整数（YAML 会给 int 类型）。

    注意纯数字**字符串**按时刻解析（"0830" → 08:30），与
    app/parser.py 的快速记录手感一致——同一串字在两个入口不该
    含义不同。要写分钟数请用不带引号的整数。
    """
    if isinstance(text, bool):
        raise ConfigError(f"时间不能是布尔值: {text!r}")
    if isinstance(text, int):
        if not (0 <= text <= DAY_MIN):
            raise ConfigError(f"分钟数须落在 0–{DAY_MIN}: {text}")
        return text
    if not isinstance(text, str):
        raise ConfigError(f"时间须是 \"HH:MM\" 或分钟数，收到 {type(text).__name__}: {text!r}")

    s = text.strip()
    if not s:
        raise ConfigError("时间为空字符串")

    if ":" not in s:
        if not s.isdigit():
            raise ConfigError(f"时间格式非法（应为 \"HH:MM\" 或纯数字分钟）: {text!r}")
        if len(s) == 4:
            h, m = int(s[:2]), int(s[2:])
        elif len(s) == 3:
            h, m = int(s[:1]), int(s[1:])
        else:
            raise ConfigError(
                f"数字时间须为 3–4 位（如 \"830\"、\"0830\"）: {text!r}；"
                f"要写分钟数请用不带引号的整数")
        if not (0 <= h <= 24) or not (0 <= m < 60):
            raise ConfigError(f"时间超出范围: {text!r}")
        total = h * 60 + m
        if total > DAY_MIN:
            raise ConfigError(f"时间超出一天（最大 24:00）: {text!r}")
        return total

    hh, _, mm = s.partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        raise ConfigError(f"时间格式非法（应为 \"HH:MM\"）: {text!r}")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 24) or not (0 <= m < 60):
        raise ConfigError(f"时间超出范围: {text!r}")
    total = h * 60 + m
    if total > DAY_MIN:
        raise ConfigError(f"时间超出一天（最大 24:00）: {text!r}")
    return total


def _parse_block(raw: Any, where: str) -> BlockSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: 块须是映射，收到 {type(raw).__name__}")

    for key in ("start", "end", "name"):
        if key not in raw:
            raise ConfigError(f"{where}: 缺少必填字段 `{key}`")

    name = raw["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: `name` 不能为空")

    try:
        start = to_minutes(raw["start"])
        end = to_minutes(raw["end"])
    except ConfigError as e:
        raise ConfigError(f"{where}: {e}") from e

    # 跨零点：end <= start 时补一天。睡眠块 22:40 → 06:30 就是这条路。
    # 这里**与模板编辑接口的取舍不同**——那边拒绝 end<=start（见 api/templates._validate），
    # 因为界面上的输入是「敲错了」概率更大；而配置文件里跨零点是有意为之的写法。
    if end <= start:
        end += DAY_MIN
    if end - start > DAY_MIN:
        raise ConfigError(f"{where}: 跨度超过一天（{end - start} 分钟）")

    cat = raw.get("category")
    if cat is not None:
        if not isinstance(cat, str):
            raise ConfigError(f"{where}: `category` 须是字符串")
        cat = cat.strip()
        if cat not in CANDIDATE_CATEGORIES:
            raise ConfigError(
                f"{where}: 未知的 category {cat!r}，候选值: {'/'.join(CANDIDATE_CATEGORIES)}")

    return BlockSpec(start_min=start, end_min=end, name=name.strip(),
                     category=cat, sort_order=raw.get("sort_order", 0))


def parse_timeline(data: Any) -> list[TemplateSpec]:
    """校验并归一化 timeline.yaml 的内容。纯函数，不读文件。"""
    if data is None:
        raise ConfigError("timeline 配置为空")
    if not isinstance(data, dict):
        raise ConfigError(f"顶层须是映射，收到 {type(data).__name__}")
    raw_templates = data.get("templates")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ConfigError("`templates` 须是非空列表")

    out: list[TemplateSpec] = []
    seen_names: set[str] = set()

    for ti, raw_t in enumerate(raw_templates):
        where = f"templates[{ti}]"
        if not isinstance(raw_t, dict):
            raise ConfigError(f"{where}: 模板须是映射")

        name = raw_t.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: 模板缺少 `name`")
        name = name.strip()
        if name in seen_names:
            raise ConfigError(f"{where}: 模板名重复 {name!r}")
        seen_names.add(name)
        where = f"templates[{ti}] ({name})"

        raw_blocks = raw_t.get("blocks")
        if not isinstance(raw_blocks, list) or not raw_blocks:
            raise ConfigError(f"{where}: `blocks` 须是非空列表")

        blocks = []
        for bi, raw_b in enumerate(raw_blocks):
            b = _parse_block(raw_b, f"{where} blocks[{bi}]")
            b.sort_order = bi        # 文件顺序即显示顺序，不额外要求写 sort_order
            blocks.append(b)

        # 块按文件顺序排列，允许有空隙（真实生活本来就有）。
        # 但不允许时间反序——那几乎一定是手编文件时把两条写颠倒了。
        for i in range(1, len(blocks)):
            if blocks[i].start_min < blocks[i - 1].start_min:
                raise ConfigError(
                    f"{where}: 第 {i + 1} 个块起始时间早于上一个"
                    f"（{blocks[i - 1].name} → {blocks[i].name}），"
                    f"文件里的块需按时间先后排列")

        out.append(TemplateSpec(
            name=name,
            description=(raw_t.get("description") or "").strip(),
            is_default=bool(raw_t.get("is_default", False)),
            blocks=blocks,
        ))

    if not any(t.is_default for t in out):
        # 没有默认模板 = 对照页直接 404（reports._compare_for 取 is_default=1）。
        # 与其运行时才发现，不如加载时就拦下。
        raise ConfigError("至少要有一个模板标 `is_default: true`，否则对照页无模板可用")
    return out


def parse_thresholds(data: Any) -> Thresholds:
    """校验并归一化 thresholds.yaml 的内容。纯函数，不读文件。"""
    if not isinstance(data, dict):
        raise ConfigError(f"thresholds 顶层须是映射，收到 {type(data).__name__}")

    def need(section: str, key: str) -> Any:
        sec = data.get(section)
        if not isinstance(sec, dict):
            raise ConfigError(f"缺少 `{section}` 段")
        if key not in sec:
            raise ConfigError(f"`{section}` 缺少 `{key}`")
        return sec[key]

    def number(section: str, key: str) -> float:
        v = need(section, key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ConfigError(f"`{section}.{key}` 须是数字，收到 {v!r}")
        return float(v)

    sleep_hours = number("sleep", "min_hours")
    if not (0 < sleep_hours <= 24):
        raise ConfigError(f"`sleep.min_hours` 须在 (0, 24] 内: {sleep_hours}")

    target = need("sleep", "target_start")
    if not isinstance(target, str):
        raise ConfigError("`sleep.target_start` 须是 \"HH:MM\" 字符串")
    try:
        to_minutes(target)
    except ConfigError as e:
        raise ConfigError(f"`sleep.target_start`: {e}") from e

    ex_lo = number("exercise", "min_minutes")
    ex_hi = number("exercise", "max_minutes")
    if not (0 < ex_lo < ex_hi):
        raise ConfigError(f"`exercise` 区间非法，需 0 < min < max: {ex_lo} / {ex_hi}")

    pr_lo = number("project", "min_minutes")
    pr_hi = number("project", "max_minutes")
    if not (0 < pr_lo < pr_hi):
        raise ConfigError(f"`project` 区间非法，需 0 < min < max: {pr_lo} / {pr_hi}")

    return Thresholds(
        sleep_min_hours=sleep_hours,
        sleep_target_start=target,
        exercise_min_minutes=int(ex_lo),
        exercise_max_minutes=int(ex_hi),
        project_min_minutes=int(pr_lo),
        project_max_minutes=int(pr_hi),
    )


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 语法错误（{path.name}）: {e}") from e


def load_timeline(path: Optional[Path] = None) -> list[TemplateSpec]:
    return parse_timeline(_read_yaml(path or TIMELINE_PATH))


def load_thresholds(path: Optional[Path] = None) -> Thresholds:
    return parse_thresholds(_read_yaml(path or THRESHOLDS_PATH))
