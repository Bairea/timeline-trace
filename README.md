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

前端有三组 Node 断言，都不依赖浏览器：

```bash
node tests/js/geom.test.js            # 时间轴几何
node tests/js/template-form.test.js   # 模板编辑页的时间解析与时长
```

DOM 级渲染与交互验证需要 jsdom，装在隔离工作区（不进项目依赖）：

```bash
NODE_PATH="$HOME/.workbuddy/binaries/node/workspace/node_modules" \
  node tests/js/template-dom.test.js
```

三组断言分别在守不同的东西：

| 文件 | 守什么 |
|---|---|
| `geom.test.js` | 各缩放倍率下的轴高、跨零点块高、以及「相对位置不随缩放改变」这条不变式——`state.zoom` 曾是倍率/像素两种语义混用的重灾区 |
| `template-form.test.js` | 编辑页的时间解析与时长计算，须与 `app/parser.py` 手感一致（两套独立实现，容易分叉） |
| `template-dom.test.js` | 真实 DOM 渲染结果与交互后果——纯逻辑全对但渲染出错是踩过的坑（轴高塌陷） |

## 运行

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

## 页面

| 路径 | 作用 |
|---|---|
| `/` | 双栏对照：左理想、右实际，记录与拖动都在这里 |
| `/static/template.html` | 模板编辑：增删改预期时间线的每个块 |
| `/static/stats.html` | 统计：日/周/月聚合、优先级四项达标率 |

## 模块职责

| 文件 | 职责 |
|---|---|
| `app/compare.py` | 对照引擎。**纯函数，无 IO** |
| `app/parser.py` | 快速记录行解析器。**纯函数，无 IO** |
| `app/db.py` | SQLite 连接与建表 |
| `app/repo.py` | 实际块数据访问（查询自动过滤软删除） |
| `app/seed.py` | 初始工作日模板 |
| `app/stats.py` | 统计聚合，只消费对照结果 |
| `app/export.py` | CSV / XLSX 生成 |
| `app/api/templates.py` | 模板与模板块 CRUD（写入校验见 `_validate`） |
| `static/template.js` | 模板编辑页逻辑 |
