# timeline-trace

理想时间线 vs 实际时间线的对照与沉淀工具。设计文档见 `docs/superpowers/specs/`，实施计划见 `docs/superpowers/plans/`。

## 环境

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
```

## 测试

```bash
.venv/Scripts/python.exe -m pytest -q          # Windows
.venv/bin/python -m pytest -q                  # macOS / Linux
```

前端时间轴几何的纯逻辑断言（不依赖浏览器，直接跑 Node）：

```bash
node tests/js/geom.test.js
```

它覆盖各缩放倍率下的轴高、跨零点块高、以及「相对位置不随缩放改变」
这条不变式——`state.zoom` 曾是倍率/像素两种语义混用的重灾区，这组
断言就是为了把这个错误钉死。

## 运行

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

## 模块职责

| 文件 | 职责 |
|---|---|
| `app/compare.py` | 对照引擎。**纯函数，无 IO** |
| `app/parser.py` | 快速记录行解析器。**纯函数，无 IO** |
| `app/db.py` | SQLite 连接与建表 |
| `app/repo.py` | 实际块数据访问（查询自动过滤软删除） |
| `app/seed.py` | 初始工作日模板 |
