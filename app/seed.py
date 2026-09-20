"""初始模板种子数据。设计文档 §2.3。

块的初始定义已搬到 `config/timeline.yaml`——改模板不必再改代码。
本模块只负责把配置**灌进数据库一次**，之后不再干预。

为什么是「一次」而不是「每次启动同步」：

  对照结果是查询时实时计算的（design §3.1 第 4 条），所以模板是
  用户会持续调整的东西。若每次启动都按 YAML 覆盖，用户在模板编辑页
  的改动会在下次重启时凭空消失——这种「改了会自己变回去」的体验
  比不能改更糟。反过来若无条件跳过，改了 YAML 又不生效，等于把
  配置化做成了摆设。

  故：仅在**该模板尚不存在**时灌入。想强制重新生成，删掉模板或
  直接改 `data/timeline.db`。`source` 列记录了模板是不是由本模块
  创建的，为将来可能需要的「重新种子化」留判断依据。
"""
import sqlite3
from datetime import datetime
from typing import Optional

from app.config import TemplateSpec, load_timeline


def seed_from_specs(conn: sqlite3.Connection,
                    specs: list[TemplateSpec]) -> list[int]:
    """按配置灌入模板。已存在的同名模板跳过（保留用户手改）。

    返回**本次新建**的模板 id 列表；已存在的不计入。
    """
    created: list[int] = []
    for spec in specs:
        existing = conn.execute(
            "SELECT id FROM templates WHERE name = ?", (spec.name,)
        ).fetchone()
        if existing:
            continue

        cur = conn.execute(
            "INSERT INTO templates (name, description, is_default, created_at, source)"
            " VALUES (?, ?, ?, ?, 'seed')",
            (spec.name, spec.description, int(spec.is_default),
             datetime.now().isoformat()),
        )
        tid = cur.lastrowid
        conn.executemany(
            "INSERT INTO template_blocks"
            " (template_id, start_min, end_min, name, category, sort_order)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(tid, b.start_min, b.end_min, b.name, b.category, b.sort_order)
             for b in spec.blocks],
        )
        created.append(tid)

    conn.commit()
    return created


def seed_default_template(conn: sqlite3.Connection,
                          config_path: Optional[object] = None) -> int:
    """灌入默认模板，返回其 id。

    向后兼容的入口：旧调用方只关心「拿到默认模板 id」。
    """
    specs = load_timeline(config_path)
    with conn:
        seed_from_specs(conn, specs)

    row = conn.execute(
        "SELECT id FROM templates WHERE is_default = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        # seed_from_specs 只在模板已存在时跳过，所以走到这里说明
        # 库里既没有配置里的模板、也没有别的默认模板——属于数据异常。
        raise RuntimeError("没有默认模板：请检查 config/timeline.yaml 或 data/timeline.db")
    return row["id"]
