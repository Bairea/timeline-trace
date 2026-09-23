# timeline-trace

理想时间线 vs 实际时间线的对照与沉淀工具。设计文档见 `docs/superpowers/specs/`，实施计划见 `docs/superpowers/plans/`。

## 环境

依赖用 [uv](https://docs.astral.sh/uv/) 管理：`pyproject.toml` 声明依赖（运行时 + dev 组），`uv.lock` 锁定精确版本。

```bash
uv sync        # 创建/同步 .venv 并安装依赖（含 dev 组：pytest、httpx）
```

服务器部署用 `uv sync --frozen --no-dev`，见 `deploy/README.md` §2。

## 测试

```bash
uv run pytest -q
```

前端有三组 Node 断言，都不依赖浏览器：

```bash
node tests/js/geom.test.js            # 时间轴几何
node tests/js/template-form.test.js   # 模板编辑页的时间解析与时长
```

DOM 级渲染与交互验证需要 jsdom，装在隔离工作区（不进项目依赖）：

```bash
# Windows / Git Bash：NODE_PATH 要用 Windows 风格路径，$HOME 展开成 /c/... 时 Node 不认
NODE_PATH="C:/Users/<你>/.workbuddy/binaries/node/workspace/node_modules" \
  node tests/js/template-dom.test.js
```

未装 jsdom 时该组会打印提示并以退出码 0 结束（不算失败），另两组不受影响。

三组断言分别在守不同的东西：

| 文件 | 守什么 |
|---|---|
| `geom.test.js` | 各缩放倍率下的轴高、跨零点块高、以及「相对位置不随缩放改变」这条不变式——`state.zoom` 曾是倍率/像素两种语义混用的重灾区 |
| `template-form.test.js` | 编辑页的时间解析与时长计算，须与 `app/parser.py` 手感一致（两套独立实现，容易分叉） |
| `template-dom.test.js` | 真实 DOM 渲染结果与交互后果——纯逻辑全对但渲染出错是踩过的坑（轴高塌陷） |

## 配置

预期时间线与统计阈值都放在 `config/`，改这些不必改代码：

| 文件 | 内容 |
|---|---|
| `config/timeline.yaml` | 初始模板与所有时间块（含 category） |
| `config/thresholds.yaml` | 优先级四项的判定阈值（睡眠下限、操练区间、项目推进区间） |

**只在首次初始化时灌入数据库，之后不再干预。** 数据库是运行时唯一真相源：

- 启动时若同名模板已存在 → 跳过，你在模板编辑页的改动不会被冲掉；
- 想按配置**重新生成**（会丢弃手改）→ 调 `app.seed.reseed_from_config(conn, "工作日")`，
  或删掉 `data/timeline.db` 重来。不给「每次启动自动同步」是因为那会让
  你在编辑页的改动在下次重启时凭空消失。

这样做的理由：对照结果是查询时实时计算的，模板本就是你会持续调整的东西。
若每次启动都按 YAML 覆盖，「改了会自己变回去」比不能改更糟；若无条件跳过，
改了 YAML 又不生效，配置化就成了摆设。

配置文件写错会**带定位信息**报错（第几个模板、第几个块、哪个字段），
不会让你对着 KeyError 猜。`app/config.py` 的解析是纯函数，测试不需要造文件。

## 运行

```bash
uv run uvicorn app.main:app --reload --port 8000
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
| `app/classify.py` | 实际块的分类推断（从模板派生，不落库）。**纯函数，无 IO**。有一处待决策的语义取舍，见 [评审报告 §4](docs/reviews/2026-09-20-template-config-review.md) |
| `app/config.py` | 加载并校验 `config/*.yaml`。解析层是纯函数 |
| `app/db.py` | SQLite 连接、建表与幂等迁移 |
| `app/repo.py` | 实际块数据访问（查询自动过滤软删除） |
| `app/seed.py` | 把配置里的模板灌进库（只灌一次） |
| `app/stats.py` | 统计聚合，只消费对照结果 |
| `app/export.py` | CSV / XLSX 生成 |
| `app/api/templates.py` | 模板与模板块 CRUD（写入校验见 `_validate`） |
| `static/template.js` | 模板编辑页逻辑 |

## 一个已知的实现偏离

设计文档 §5.4 定义优先级四项时用了 `category`，但 **`actual_blocks` 表没有
`category` 列**（只有 `template_blocks` 有）。故 `app/classify.py` 把分类做成
**派生值**：实际块经名字与时间对照，找到它落在哪个模板块内，取该模板块的
category。这与「对照结果不落库、改模板即重算历史」是同一条设计原则。

此前 `app/stats.py` 用块名子串硬凑（`"操" in name`、`"干活" in name`），
实测确认会漏算：用户快速记录不写名字时 parser 填「未命名」，
这些块永远进不了统计。现已改为基于分类判定。

另外一个容易虚高的场景已被测试守住：模板「干活 20:30–22:00」时段内
刷 30 分钟短视频，**不会**被算成项目推进（见
`tests/test_api_export.py::test_stats_excludes_unrelated_block_inside_template_span`）。

## 评审

`docs/reviews/` 存独立的代码评审报告。最新一份
[2026-09-20-template-config-review.md](docs/reviews/2026-09-20-template-config-review.md)
覆盖模板编辑与 YAML 配置化两次改动，记录了 1 个 P0（已修）、4 个 P2（已修）、
**2 个经实测撤回的误报**，以及 1 个待决策的语义取舍。
