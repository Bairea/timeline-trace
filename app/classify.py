"""实际块的分类推断。设计文档 §5.4。

背景：`actual_blocks` 表没有 `category` 列，而 §5.4 的度量口径
（「运动 = category=身体锚点 的块」「项目推进 = category=项目推进 的
实际块总时长」）都建立在分类之上。此前 stats.py 用名字子串硬凑
（`"操" in name or "练" in name`、`"干活" in name`），有两个问题：

1. **会漏算。** 用户快速记录时不写名字，parser 会填 `未命名`，
   于是这些块永远进不了「项目推进」统计。已实测确认。
2. **分类定义在模板里、判定写在代码里**，两处各说各话。用户把
   模板块改名或改 category，统计口径不会跟着变。

本模块的做法：**不新增数据库列，把分类做成派生值。** 实际块经由
对照关系找到它落在哪个模板块的时间范围内，取该模板块的 category。
这与「对照结果不落库、改模板即重算历史」是同一条设计原则
（design §3.1 第 4 条）——分类也随模板一起演化。

匹配规则按优先级从精确到宽松：

  1. 名字完全一致。
  2. 名字互相包含（模板名是「干活（中间做拉伸）」，实际块名是「干活」）。
     去掉模板名里的括注后比较，避免「午饭与午休」这种带说明的名字
     永远匹配不上实际块打的「午饭」。
  3. 时间兜底：**重叠占模板块比例**达标。只在名字毫无线索时才用，
     且必须占模板块一半以上，即整个模板块时段基本都花在这件事上。

为什么第 3 条要卡「占模板块比例」而不是「占实际块比例」：

  实测场景——模板「干活 20:30–22:00」90 分钟，用户记了
  「干活 20:30–21:10」40 分钟和「短视频 21:10–21:40」30 分钟。
  两者都 100% 落在模板块内。若按「占实际块比例」判定，短视频
  会被归成项目推进，于是该指标虚高 30 分钟。而「干活时段里刷视频」
  恰是最常见的模式，这个偏差会系统性累积。

  按「占模板块比例」判定则短视频只占 33%，落榜 → 计入「其他」，
  不再污染项目推进。代价是「干活」本身（占 44%）也会落榜——
  但它有名字，由第 2 条接住。这正是名字优先于时间的原因：
  用户打了名字，意图比时间区间明确。
"""
from typing import Iterable, Optional

UNCATEGORIZED = "其他"

# 名字比较时从模板名里剥掉的括注形式。
# 模板名常带说明（「出门前准备（刮胡子…）」「干活（中间做拉伸）」），
# 而实际块几乎不会照抄括注部分。
_BRACKETS = "（(【["


def _base_name(name: str) -> str:
    """取名字的主干：截断到第一个左括号之前。"""
    s = (name or "").strip()
    for ch in _BRACKETS:
        idx = s.find(ch)
        if idx > 0:
            s = s[:idx]
    return s.strip()


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def infer_category(actual: dict, template_blocks: Iterable[dict]) -> str:
    """推断单个实际块的 category。找不到依据则返回 UNCATEGORIZED。

    `template_blocks` 为字典序列，需含 start_min / end_min / name / category。
    """
    if actual.get("end_min") is None:
        return UNCATEGORIZED

    a_start, a_end = actual["start_min"], actual["end_min"]
    a_name = (actual.get("name") or "").strip()

    candidates = [t for t in template_blocks if t.get("category")]
    if not candidates:
        return UNCATEGORIZED

    # 1. 名字完全一致
    if a_name:
        for t in candidates:
            if (t.get("name") or "").strip() == a_name:
                return t["category"]

        # 2. 去括注后互相包含
        a_base = _base_name(a_name)
        if a_base:
            for t in candidates:
                t_base = _base_name(t.get("name"))
                if t_base and (t_base == a_base
                               or t_base in a_base or a_base in t_base):
                    return t["category"]

    # 3. 时间兜底：重叠须占模板块一半以上
    from app.compare import MIN_OVERLAP_RATIO
    best_cat, best_ov = None, 0
    for t in candidates:
        span = t["end_min"] - t["start_min"]
        if span <= 0:
            continue
        ov = _overlap(a_start, a_end, t["start_min"], t["end_min"])
        if ov > best_ov and (ov / span) >= MIN_OVERLAP_RATIO:
            best_cat, best_ov = t["category"], ov
    return best_cat or UNCATEGORIZED


def infer_category_map(actual_rows: list[dict],
                       template_blocks: list[dict]) -> dict[int, str]:
    """批量推断，返回 {实际块 id: category}。

    以 id 为键是因为同一天可能出现多个同名块，用名字做键会互相覆盖。
    """
    out: dict[int, str] = {}
    for r in actual_rows:
        if "id" in r:
            out[r["id"]] = infer_category(r, template_blocks)
    return out


def category_of(row: dict, categories: Optional[dict[int, str]]) -> str:
    """取某实际块的分类。调用方未提供映射时退回 UNCATEGORIZED。"""
    if not categories:
        return UNCATEGORIZED
    return categories.get(row.get("id"), UNCATEGORIZED)
