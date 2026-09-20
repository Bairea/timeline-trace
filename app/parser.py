"""快速记录行解析器。纯函数，无 IO。设计文档 §7。"""
import re
from dataclasses import dataclass
from typing import Optional

MAX_SPAN_MIN = 16 * 60
DEFAULT_DURATION_MIN = 30


class ParseError(ValueError):
    """解析失败，消息中必须包含原始文本。"""


@dataclass
class ParsedBlock:
    start_min: int
    end_min: Optional[int]
    name: str


def _normalize(text: str) -> str:
    """全角转半角，统一分隔符。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    s = "".join(out)
    return s.replace("。", ".").replace("：", ":").replace("－", "-").replace("—", "-")


_TIME = r"(?:\d{1,2}[:.]\d{1,2}|\d{3,4})"


def _to_min(token: str) -> int:
    token = token.strip()
    if ":" in token or "." in token:
        h, m = re.split(r"[:.]", token, maxsplit=1)
        h, m = int(h), int(m)
    else:
        if len(token) == 4:
            h, m = int(token[:2]), int(token[2:])
        elif len(token) == 3:
            h, m = int(token[:1]), int(token[1:])
        else:
            raise ValueError(token)
    if not (0 <= h <= 24) or not (0 <= m < 60):
        raise ValueError(token)
    total = h * 60 + m
    if total > 24 * 60:
        raise ValueError(token)
    return total


_PATTERN = re.compile(
    rf"^\s*(?P<start>{_TIME})\s*(?P<sep>-|~|至)?\s*(?P<end>{_TIME})?\s*(?P<name>.*)$"
)


def parse_line(line: str, prev_end: Optional[int], now_min: int,
               fallback_name: str = "未命名") -> ParsedBlock:
    raw = line
    text = _normalize(line).strip()
    if not text:
        raise ParseError(f"空输入: {raw}")

    m = _PATTERN.match(text)
    if not m or not m.group("start"):
        raise ParseError(f"无法解析时间: {raw}")

    try:
        start = _to_min(m.group("start"))
    except ValueError:
        raise ParseError(f"时间超出范围或格式非法: {raw}")

    sep = m.group("sep")
    end_token = m.group("end")
    name = m.group("name").strip() or fallback_name

    if sep and not end_token:
        return ParsedBlock(start_min=start, end_min=None, name=name)  # 开放区间

    if end_token:
        try:
            end = _to_min(end_token)
        except ValueError:
            raise ParseError(f"时间超出范围或格式非法: {raw}")
        if end <= start:
            end += 24 * 60  # 跨零点
        if end - start > MAX_SPAN_MIN:
            raise ParseError(f"跨度超过 16 小时，疑似敲错: {raw}")
        return ParsedBlock(start_min=start, end_min=end, name=name)

    # 只有起点：接上一块终点，否则从 now 起算
    anchor = prev_end if prev_end is not None else now_min
    if start < anchor and start < now_min:
        start += 24 * 60
    return ParsedBlock(start_min=start, end_min=start + DEFAULT_DURATION_MIN, name=name)
