"""快速记录行解析器。纯函数，无 IO。设计文档 §7。

支持的行格式（实测矩阵见 tests/test_parser.py）：

    20:30-21:10 干活      标准区间（分隔符 -/~/至，两侧空格随意）
    20.30-21.10 干活      点号当冒号
    2030-2110 干活        紧凑 HHMM
    20:30- 干活           开放区间（终点待下一次记录补）
    22:40-06:30 睡觉      跨零点（终点小于起点即加一天）
    08:30 09:30           纯空格分隔的区间（省略分隔符）
    08:30 干活            只有起点 → 接上一块终点，否则 +30 分钟
    08:30 20:30-21:30     第二个时刻属于**名字**，不是终点

最后一条是 2026-09-20 修掉的缺陷。原实现用单条正则

    ^(start)(?:\\s*(sep)|\\s+)(end)?\\s*(name.*)$

其中 `sep` 与 `end` 都是可选组，于是正则引擎在 `08:30 20:30-21:30` 上
会先让 `sep` 取 None、再让 `end` 吞掉 `20:30`（因为「可选」不要求前置），
得到 08:30→20:30 的 **12 小时**块，而 `-21:30` 被塞进名字。
带名字时更糟：`08:30 20:30-21:30 干活` 的名字变成 `-21:30 干活`，
**用户写的内容直接丢了一半**。

**分组正则无法表达「终点的存在依赖于分隔符」这种依赖关系**，
故改为分层：`_HEAD` 只拆出起点，剩下的分隔符 / 终点 / 名字
由 `_split()` 顺序判断。**不要为了「简洁」把它合回单条正则**——
合回去必然重新引入上述缺陷。
"""
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


# 只负责拆出「起点」，剩余部分（分隔符 / 终点 / 名字）手工判断。
#
# 不用单条大正则的原因是：当「分隔符」和「终点」都可选时，正则引擎
# 会优先让终点组吞掉下一个时刻——`08:30 20:30-21:30` 于是被解析成
# 08:30→20:30 的 12 小时块，名字被 `-21:30` 污染。分组正则无法表达
# 「终点必须以分隔符为前置」这种依赖关系，只能分层做。
_HEAD = re.compile(rf"^\s*(?P<start>{_TIME})\s*(?P<rest>.*)$")

# 分隔符（可紧贴、也可两侧带空格）
_SEP = re.compile(r"^(?P<sep>-|~|至)\s*")

# 剩余部分开头的时刻
_LEAD_TIME = re.compile(rf"^(?P<tok>{_TIME})(?P<tail>\s*.*)$")


def _split(text: str):
    """把一行拆成 (start_tok, sep, end_tok, name)。

    规则：
    - 起点后紧跟 `-`/`~`/`至` → 是显式分隔符，后面若有时刻即为终点；
      没有时刻则是开放区间（end_tok=None 且 sep 非空）。
    - 起点后是纯空格 + 另一个时刻 → 视为区间（用户省略了分隔符），
      但要求那个时刻之后**不跟分隔符**；否则说明它是在描述一个区间，
      属于名字（`12:00 20:30-21:30 复盘`）。
    - 其余情况第二个时刻都在名字里。
    """
    m = _HEAD.match(text)
    if not m:
        return None
    start_tok = m.group("start")
    rest = m.group("rest")

    ms = _SEP.match(rest)
    if ms:
        after = rest[ms.end():]
        mt = _LEAD_TIME.match(after)
        if mt:
            return start_tok, ms.group("sep"), mt.group("tok"), \
                mt.group("tail").strip()
        return start_tok, ms.group("sep"), None, after.strip()

    mt = _LEAD_TIME.match(rest)
    if mt and not re.match(r"\s*[-~至]", mt.group("tail")):
        return start_tok, None, mt.group("tok"), mt.group("tail").strip()

    return start_tok, None, None, rest.strip()


def parse_line(line: str, prev_end: Optional[int], now_min: int,
               fallback_name: str = "未命名") -> ParsedBlock:
    raw = line
    text = _normalize(line).strip()
    if not text:
        raise ParseError(f"空输入: {raw}")

    parts = _split(text)
    if not parts:
        raise ParseError(f"无法解析时间: {raw}")
    start_tok, sep, end_token, name = parts

    try:
        start = _to_min(start_tok)
    except ValueError:
        raise ParseError(f"时间超出范围或格式非法: {raw}")

    name = name or fallback_name

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
