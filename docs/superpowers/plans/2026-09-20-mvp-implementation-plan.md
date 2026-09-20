# timeline-trace 实施计划

> 设计依据：`docs/superpowers/specs/2026-09-20-timeline-trace-design.md`
> 分支：`feature/mvp`
> 任务粒度：每个 2–5 分钟可完成，含精确文件路径与验证命令

---

## 阶段划分

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P0 | 项目骨架与依赖 | `pytest` 可运行，空测试全绿 |
| P1 | 纯逻辑层（compare / parser） | 单元测试穷举边界全绿 |
| P2 | 数据层（db / models） | 建表成功，CRUD 测试通过 |
| P3 | API 层（templates / actual / reports） | pytest + httpx 接口测试通过 |
| P4 | 导出（CSV / XLSX） | 导出文件可被 Excel 正确打开 |
| P5 | 前端单页（对照视图 + 记录框 + 块操作） | 手测记录/编辑/删除全流程 |
| P6 | 统计视图 | 日/周/月聚合正确 |
| P7 | 部署与安全（自签证书 + nginx + systemd） | 公网 HTTPS 可访问，未授权返回 401 |

**建议执行顺序：P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7**

P1 必须先于 P2/P3 —— 对照引擎和解析器是整个系统的真实逻辑，放在前面用测试固定住行为，后面接数据库和 API 时才有确定性可依赖。

---

## P0 · 项目骨架与依赖

### 任务 0.1：创建目录结构

- 文件路径：项目根 `D:\Desktopfile\chores\timeline-trace\`
- 执行：

```bash
mkdir -p app/api static tests data
touch app/__init__.py app/api/__init__.py tests/__init__.py
```

- 验证：`ls app` 应显示 `__init__.py  api`

### 任务 0.2：写依赖清单

- 文件路径：`requirements.txt`
- 内容：

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
openpyxl==3.1.5
pytest==8.3.4
httpx==0.28.1
```

- 验证：`python -m venv .venv && .venv/Scripts/pip install -r requirements.txt` 无报错

### 任务 0.3：写 pytest 配置

- 文件路径：`pytest.ini`
- 内容：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
```

- 验证：`.venv/Scripts/pytest` 应输出 `no tests ran`（退出码 5），说明配置被识别

### 任务 0.4：创建空测试并确认基线绿

- 文件路径：`tests/test_compare.py`
- 内容：

```python
def test_placeholder():
    assert True
```

- 验证：`.venv/Scripts/pytest -q` 输出 `1 passed`

---

## P1 · 纯逻辑层

### 任务 1.1：定义比对结果数据结构

- 文件路径：`app/compare.py`
- 内容（文件开头）：

```python
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
```

- 验证：`.venv/Scripts/pytest -q` 仍 `1 passed`（未破坏既有测试）

### 任务 1.2：实现重叠计算（RED → GREEN）

- 文件路径：`tests/test_compare.py`
- 先写测试（RED）：

```python
from app.compare import overlap_minutes


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
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 **FAIL**（`ImportError: cannot import name 'overlap_minutes'`）——确认测试确实在守卫东西
- 文件路径：`app/compare.py`
- 加实现（GREEN）：

```python
def overlap_minutes(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """两个区间的重叠分钟数。首尾相接视为 0。"""
    return max(0, min(a_end, b_end) - max(a_start, b_start))
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 **5 passed**

### 任务 1.3：实现单条比对判定（RED → GREEN）

- 文件路径：`tests/test_compare.py`
- 先写测试（RED）：

```python
from app.compare import BlockLike, compare_block


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
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 FAIL（`cannot import name 'compare_block'`）
- 文件路径：`app/compare.py`
- 加实现（GREEN）：

```python
def compare_block(tpl: BlockLike, actuals: list[BlockLike]) -> BlockComparison:
    """把单个模板块与该日所有实际块比对，取最优结果。"""
    best: Optional[BlockComparison] = None

    for act in actuals:
        ov = overlap_minutes(tpl.start_min, tpl.end_min, act.start_min, act.end_min)
        if ov == 0:
            continue

        delta_start = act.start_min - tpl.start_min
        delta_dur = (act.end_min - act.start_min) - (tpl.end_min - tpl.start_min)
        tpl_dur = tpl.end_min - tpl.start_min
        ratio = ov / tpl_dur if tpl_dur else 0.0

        within_tolerance = abs(delta_start) <= TOLERANCE_MIN and abs(delta_dur) <= TOLERANCE_MIN
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


_RANK = {"unrecorded": 0, "offset": 1, "aligned": 2}


def _rank(c: BlockComparison) -> tuple:
    """对齐度评分：先比状态档位，再比重叠时长。"""
    return (_RANK[c.status], c.overlap_min)
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 **11 passed**

### 任务 1.4：实现一日完整比对并标出计划外（RED → GREEN）

- 文件路径：`tests/test_compare.py`
- 先写测试（RED）：

```python
from app.compare import compare_day


def test_compare_day_marks_unplanned():
    tpls = [BlockLike(1230, 1320, "干活")]
    acts = [BlockLike(1230, 1270, "干活"), BlockLike(1270, 1290, "短视频")]
    results = compare_day(tpls, acts)
    statuses = {r.status for r in results}
    assert "unplanned" in statuses
    unplanned = [r for r in results if r.status == "unplanned"]
    assert unplanned[0].actual_name == "短视频"
    assert unplanned[0].template_name is None


def test_compare_day_returns_one_row_per_actual_plus_unrecorded_templates():
    tpls = [BlockLike(390, 420, "早操"), BlockLike(1320, 1340, "晚练")]
    acts = [BlockLike(395, 422, "早操"), BlockLike(1270, 1290, "短视频")]
    results = compare_day(tpls, acts)
    # 早操 → aligned；晚练 → unrecorded；短视频 → unplanned
    assert len(results) == 3
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 FAIL
- 文件路径：`app/compare.py`
- 加实现（GREEN）：

```python
def compare_day(template_blocks: list[BlockLike],
                actual_blocks: list[BlockLike]) -> list[BlockComparison]:
    """一日对照。输出 = 每个模板块一行（unrecorded 时仅模板侧）
    + 每个未命中任何模板块的实际块一行（unplanned）。"""
    results: list[BlockComparison] = []
    matched_actuals: set[int] = set()

    for tpl in template_blocks:
        cmp = compare_block(tpl, actual_blocks)
        results.append(cmp)
        if cmp.actual_name is not None:
            for i, act in enumerate(actual_blocks):
                if (act.name == cmp.actual_name
                        and act.start_min == cmp.actual_start
                        and act.end_min == cmp.actual_end):
                    matched_actuals.add(i)

    for i, act in enumerate(actual_blocks):
        if i in matched_actuals:
            continue
        if any(overlap_minutes(act.start_min, act.end_min, t.start_min, t.end_min) > 0
               for t in template_blocks):
            continue
        results.append(BlockComparison(
            template_name=None, actual_name=act.name,
            template_start=None, template_end=None,
            actual_start=act.start_min, actual_end=act.end_min,
            status="unplanned", overlap_min=0,
            delta_start_min=None, delta_dur_min=None,
        ))

    return results
```

- 验证：`.venv/Scripts/pytest tests/test_compare.py -q` 应 **13 passed**

### 任务 1.5：实现快速记录解析器（RED → GREEN）

- 文件路径：`tests/test_parser.py`
- 先写测试（RED）：

```python
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
```

- 验证：`.venv/Scripts/pytest tests/test_parser.py -q` 应 FAIL（`No module named 'app.parser'`）
- 文件路径：`app/parser.py`
- 加实现（GREEN）：

```python
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
```

- 验证：`.venv/Scripts/pytest tests/test_parser.py -q` 应 **11 passed**

---

## P2 · 数据层

### 任务 2.1：建表脚本

- 文件路径：`app/db.py`
- 内容：

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "timeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  is_default  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS template_blocks (
  id          INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  start_min   INTEGER NOT NULL,
  end_min     INTEGER NOT NULL,
  name        TEXT NOT NULL,
  category    TEXT,
  sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS day_instances (
  date        TEXT PRIMARY KEY,
  template_id INTEGER REFERENCES templates(id),
  note        TEXT
);
CREATE TABLE IF NOT EXISTS actual_blocks (
  id               INTEGER PRIMARY KEY,
  date             TEXT NOT NULL,
  start_min        INTEGER NOT NULL,
  end_min          INTEGER,
  name             TEXT NOT NULL,
  is_low_stimulus  INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  deleted_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_actual_date
  ON actual_blocks(date) WHERE deleted_at IS NULL;
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

- 文件路径：`tests/test_db.py`
- 内容：

```python
from app.db import connect, init_db, SCHEMA


def test_init_db_creates_all_tables(tmp_path, monkeypatch):
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    conn = db.connect()
    db.init_db(conn)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"templates", "template_blocks", "day_instances", "actual_blocks"} <= names


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    conn = db.connect()
    db.init_db(conn)
    db.init_db(conn)  # 不应抛错
```

- 验证：`.venv/Scripts/pytest tests/test_db.py -q` 应 **2 passed**

### 任务 2.2：写入初始工作日模板

- 文件路径：`app/seed.py`
- 内容：按设计文档 §2.3 的 18 行表格插入 `templates` + `template_blocks`
- 验证：新增 `tests/test_seed.py`，断言模板块数量为 18，且第一块为 `(390, 420, "早操")`、最后一块为 `(1360, 1830, "睡觉")`

### 任务 2.3：实际块 CRUD

- 文件路径：`app/repo.py`
- 函数清单（每个配一个测试）：
  - `insert_actual(conn, date, start_min, end_min, name) -> int`
  - `update_actual(conn, block_id, **fields) -> None`
  - `soft_delete_actual(conn, block_id) -> None`
  - `restore_actual(conn, block_id) -> None`（撤销）
  - `list_actual(conn, date) -> list[dict]`（自动过滤 `deleted_at IS NULL`）
- 验证：`.venv/Scripts/pytest tests/test_repo.py -q` 全绿，重点覆盖软删除过滤

---

## P3 · API 层

### 任务 3.1：应用骨架与健康检查

- 文件路径：`app/main.py`
- 内容：创建 FastAPI 实例、启动时 `init_db`、挂载 `static/`、暴露 `GET /api/health` 返回 `{"ok": true}`
- 验证：`.venv/Scripts/pytest tests/test_api.py -q`，用 `httpx.ASGITransport` 断言 200

### 任务 3.2：访问口令认证中间件

- 文件路径：`app/auth.py`
- 内容：读环境变量 `APP_PASSWORD`；`POST /api/login` 校验口令后签发 HttpOnly Cookie；中间件拦截除 `/api/login`、`/api/health`、静态首页外的所有请求，未授权返回 401
- 验证：新增 `tests/test_auth.py`：无 Cookie 访问 `/api/actual` 返回 401；正确口令后可访问

### 任务 3.3：模板接口

- 文件路径：`app/api/templates.py`
- 端点：`GET /api/templates`、`GET /api/templates/{id}/blocks`、`POST /api/templates/{id}/blocks`、`PUT /api/template-blocks/{id}`、`DELETE /api/template-blocks/{id}`
- 验证：`tests/test_api_templates.py` 覆盖增删改查

### 任务 3.4：实际块接口 + 快速记录

- 文件路径：`app/api/actual.py`
- 端点：
  - `GET /api/actual?date=YYYY-MM-DD`
  - `POST /api/actual/quick`（body: `{"date": "...", "line": "..."}`）→ 调 `parse_line`
  - `PUT /api/actual/{id}`
  - `DELETE /api/actual/{id}`（软删除）
  - `POST /api/actual/{id}/restore`（撤销）
- 错误处理按设计文档 §7.3：解析失败返回 422 + 原文本
- 验证：`tests/test_api_actual.py`，重点断言 422 响应体含原始文本

### 任务 3.5：对照接口

- 文件路径：`app/api/reports.py`
- 端点：`GET /api/compare?date=YYYY-MM-DD` → 读模板块与实际块，调 `compare_day`，返回 JSON
- 验证：`tests/test_api_compare.py` 断言返回行数与状态分布

---

## P4 · 导出

### 任务 4.1：CSV 导出

- 文件路径：`app/export.py`，函数 `export_csv(rows) -> str`
- 要点：UTF-8 BOM 前缀 `\ufeff`；用 `csv.writer` 保证含逗号的字段正确转义；跨零点时间还原为 `22:40 / 06:30`
- 验证：`tests/test_export.py` 断言首字符为 `\ufeff`，且名称含逗号的行被正确加引号

### 任务 4.2：XLSX 导出

- 文件路径：`app/export.py`，函数 `export_xlsx(rows, daily_summary, range_stats) -> bytes`
- 要点：openpyxl 三个 sheet（明细 / 日汇总 / 区间统计）
- 验证：写盘后用 openpyxl 回读，断言 sheet 名与行数

### 任务 4.3：导出端点

- 文件路径：`app/api/reports.py`
- 端点：`GET /api/export?start=...&end=...&format=csv|xlsx`
- 验证：`tests/test_api_export.py` 断言 Content-Type 与 Content-Disposition

---

## P5 · 前端单页

### 任务 5.1：页面骨架与 24h 垂直轴

- 文件路径：`static/index.html`、`static/style.css`
- 内容：左右两栏；每栏渲染一条 24h 垂直轴（`1 分钟 = 0.75px`，全天 1080px）；顶部日期选择器
- 验证：浏览器打开 `http://127.0.0.1:8000`，两栏轴可见

### 任务 5.2：块渲染与状态配色

- 文件路径：`static/app.js`
- 内容：拉 `/api/compare`，按 `status` 上色（aligned 绿 / offset 橙 / unrecorded 灰 / unplanned 红）
- 验证：接入种子数据后颜色正确

### 任务 5.3：快速记录框

- 文件路径：`static/index.html` + `static/app.js`
- 内容：底部输入框，回车提交 `/api/actual/quick`；422 时在输入框下方标红并**保留输入内容**
- 验证：手测输入 `20:30-21:10 干活` 后块出现在右栏

### 任务 5.4：块的可视化操作

- 文件路径：`static/app.js`
- 内容：
  - 悬停显示 `×` → 删除 → 右下角 toast 带「撤销」5 秒
  - 拖动整块改位置、拖边缘改时长（`pointerdown/move/up`）
  - 双击块名就地编辑
  - 选中后 `↑↓` 挪 5 分钟、`Shift+↑↓` 挪 15 分钟
- 验证：手测删除后撤销能恢复

### 任务 5.5：批量框选

- 文件路径：`static/app.js`
- 内容：轴上 `Shift` 拖出选框，选中多个块后统一删除/移动
- 验证：手测一次删三块

---

## P6 · 统计视图

### 任务 6.1：日汇总

- 文件路径：`app/stats.py`，函数 `daily_summary(comparisons) -> dict`
- 验证：`tests/test_stats.py` 断言各类目时长之和不超 1440 分钟

### 任务 6.2：区间聚合与优先级四项

- 文件路径：`app/stats.py`
- 函数：`range_stats(conn, start, end) -> dict`，含睡眠达标率、早操出勤率、低刺激时段存在率、项目推进时长
- 验证：`tests/test_stats.py`，用手工构造的 3 天数据断言比率

### 任务 6.3：统计页

- 文件路径：`static/stats.html` + `static/stats.js`
- 验证：手测周视图数字与导出 CSV 手工计算一致

---

## P7 · 部署与安全

### 任务 7.1：systemd 服务单元

- 文件路径：`deploy/timeline-trace.service`
- 内容：`ExecStart` 指向 venv 内 uvicorn，`--host 127.0.0.1`，`Restart=always`
- 验证：`systemctl status timeline-trace` 显示 active

### 任务 7.2：自签证书与 nginx 配置

- 文件路径：`deploy/nginx.conf`、`deploy/gen-cert.sh`
- 内容：
  - `gen-cert.sh`：`openssl req -x509 -newkey rsa:4096 -days 3650 -nodes`，CN 填公网 IP
  - nginx：443 → `127.0.0.1:8000`，80 端口不开放
- 验证：浏览器访问 `https://<公网IP>`，首次点「继续访问」后能打开

### 任务 7.3：安全组与备份

- 文件路径：`deploy/backup.sh`（放服务器 crontab）
- 内容：`sqlite3 data/timeline.db ".backup 'backups/timeline-$(date +%F).db'"`，保留 30 天
- 手动步骤（写入 `deploy/README.md`）：安全组仅开 443 与 22
- 验证：手动触发一次，`backups/` 下出现当日文件

---

## 风险与注意

1. **P1 的 TDD 顺序不能倒。** 先跑测试看它红，再写实现。设计文档 §5 的判定规则是系统里唯一有真实逻辑的地方，这里不牢，后面全飘。
2. **P5 的拖动是工作量最大的一块。** 原生 JS 做 `pointerdown/move/up` 加吸附逻辑，容易写得纠缠。建议先实现"只能删和改名字"，确认可用后再加拖动。
3. **跨零点块的分钟数边界**在处理 `end_min > 1440` 时最容易出错，测试里已埋了 `1360..1830` 的用例，改动时别删。
4. **`_to_min` 对 `24:00` 的处理**：当前允许 `total == 1440`，导出时需确认不会被误判为次日 00:00。

---

## 计划变更记录

（计划变了就回头改这里，不要悄悄改上游）
