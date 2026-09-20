"""对照引擎。纯函数，无 IO。设计文档 §5。"""
from dataclasses import dataclass
from typing import Literal, Optional

Status = Literal["aligned", "offset", "unrecorded", "unplanned"]
TOLERANCE_MIN = 15  # 容差分钟数，设计文档 §5.2


@dataclass
class BlockLike:
    """模板块与实际块的共同视图。时间均为自 00:00 起的分钟数。"""
    start_min: int
    end_min: int          # 跨零点时 > 1440
    name: str


@dataclass
class BlockComparison:
    template_name: Optional[str]
    actual_name: Optional[str]
    template_start: Optional[int]
    template_end: Optional[int]
    actual_start: Optional[int]
    actual_end: Optional[int]
    status: Status
    overlap_min: int
    delta_start_min: Optional[int]
    delta_dur_min: Optional[int]


def overlap_minutes(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """两个区间的重叠分钟数。首尾相接视为 0。"""
    return max(0, min(a_end, b_end) - max(a_start, b_start))


_RANK = {"unrecorded": 0, "offset": 1, "aligned": 2}


def _rank(c: BlockComparison) -> tuple:
    """对齐度评分：先比状态档位，再比重叠时长。"""
    return (_RANK[c.status], c.overlap_min)


def compare_block(tpl: BlockLike, actuals: list[BlockLike]) -> BlockComparison:
    """把单个模板块与该日所有实际块比对，取最优结果。"""
    best: Optional[BlockComparison] = None
    tpl_dur = tpl.end_min - tpl.start_min

    for act in actuals:
        ov = overlap_minutes(tpl.start_min, tpl.end_min, act.start_min, act.end_min)
        if ov == 0:
            continue

        delta_start = act.start_min - tpl.start_min
        delta_dur = (act.end_min - act.start_min) - tpl_dur
        ratio = ov / tpl_dur if tpl_dur else 0.0

        within_tolerance = (abs(delta_start) <= TOLERANCE_MIN
                            and abs(delta_dur) <= TOLERANCE_MIN)
        status: Status = "aligned" if (ratio >= 0.6 and within_tolerance) else "offset"

        cand = BlockComparison(
            template_name=tpl.name, actual_name=act.name,
            template_start=tpl.start_min, template_end=tpl.end_min,
            actual_start=act.start_min, actual_end=act.end_min,
            status=status, overlap_min=ov,
            delta_start_min=delta_start, delta_dur_min=delta_dur,
        )
        if best is None or _rank(cand) > _rank(best):
            best = cand

    if best is None:
        return BlockComparison(
            template_name=tpl.name, actual_name=None,
            template_start=tpl.start_min, template_end=tpl.end_min,
            actual_start=None, actual_end=None,
            status="unrecorded", overlap_min=0,
            delta_start_min=None, delta_dur_min=None,
        )
    return best


def compare_day(template_blocks: list[BlockLike],
                actual_blocks: list[BlockLike]) -> list[BlockComparison]:
    """一日对照。

    不变式：**每个实际块必须至少出现在输出中一行**，绝不静默丢弃。
    输出 = 每个模板块一行（可能为 unrecorded）
         + 每个未被任何模板块行引用的实际块一行（offset 或 unplanned）。

    未被引用 ≠ 无重叠：一个实际块可能与某模板块重叠，但该模板块的
    「最优结果」被另一个实际块赢得，此时该实际块仍未出现在结果里，
    必须补齐一行，否则记录会凭空消失。
    """
    results: list[BlockComparison] = []

    for tpl in template_blocks:
        results.append(compare_block(tpl, actual_blocks))

    referenced: set[int] = set()
    for r in results:
        if r.actual_start is None:
            continue
        for i, act in enumerate(actual_blocks):
            if act.start_min == r.actual_start and act.end_min == r.actual_end:
                referenced.add(i)

    for i, act in enumerate(actual_blocks):
        if i in referenced:
            continue
        # 该实际块未被任何模板块行引用，补齐一行
        hits = [t for t in template_blocks
                if overlap_minutes(act.start_min, act.end_min, t.start_min, t.end_min) > 0]
        if hits:
            # 与某模板块有交集，但该模板块的最优结果被别的块赢得 → offset
            tpl = hits[0]
            tpl_dur = tpl.end_min - tpl.start_min
            results.append(BlockComparison(
                template_name=tpl.name, actual_name=act.name,
                template_start=tpl.start_min, template_end=tpl.end_min,
                actual_start=act.start_min, actual_end=act.end_min,
                status="offset", overlap_min=overlap_minutes(
                    act.start_min, act.end_min, tpl.start_min, tpl.end_min),
                delta_start_min=act.start_min - tpl.start_min,
                delta_dur_min=(act.end_min - act.start_min) - tpl_dur,
            ))
        else:
            results.append(BlockComparison(
                template_name=None, actual_name=act.name,
                template_start=None, template_end=None,
                actual_start=act.start_min, actual_end=act.end_min,
                status="unplanned", overlap_min=0,
                delta_start_min=None, delta_dur_min=None,
            ))

    return results
