"""初始工作日模板种子数据。设计文档 §2.3。"""
import sqlite3
from datetime import datetime

# (start_min, end_min, name, category)
WORKDAY_BLOCKS: list[tuple[int, int, str, str]] = [
    (390, 420, "早操", "身体锚点"),
    (420, 435, "洗漱", "事务"),
    (440, 450, "早饭", "事务"),
    (450, 455, "出门前准备（刮胡子、涂芦荟胶、拿手机耳机工卡、带伞）", "事务"),
    (455, 510, "通勤、听书、走路", "通勤"),
    (510, 720, "工作", "项目推进"),
    (720, 765, "午饭与午休", "事务"),
    (765, 1020, "工作", "项目推进"),
    (1020, 1050, "小结与规划后续行动", "事务"),
    (1050, 1130, "通勤、听书", "通勤"),
    (1130, 1170, "做饭", "事务"),
    (1170, 1200, "吃饭（别刷视频，最多看书）", "事务"),
    (1200, 1215, "收拾与准备早饭，内务（扫地拖地洗衣服丢垃圾）", "事务"),
    (1215, 1230, "读书 / 练字，保持平和心态", "情绪稳定"),
    (1230, 1320, "干活（中间做拉伸）", "项目推进"),
    (1320, 1340, "洗澡", "事务"),
    (1340, 1360, "晚练", "身体锚点"),
    (1360, 1830, "睡觉", "睡眠"),
]

DEFAULT_TEMPLATE_NAME = "工作日"


def seed_default_template(conn: sqlite3.Connection) -> int:
    """插入默认工作日模板。已存在同名模板则直接返回其 id（幂等）。"""
    existing = conn.execute(
        "SELECT id FROM templates WHERE name = ?", (DEFAULT_TEMPLATE_NAME,)
    ).fetchone()
    if existing:
        return existing["id"]

    cur = conn.execute(
        "INSERT INTO templates (name, description, is_default, created_at)"
        " VALUES (?, ?, 1, ?)",
        (DEFAULT_TEMPLATE_NAME, "可无限重复的工作日模板", datetime.now().isoformat()),
    )
    tid = cur.lastrowid

    conn.executemany(
        "INSERT INTO template_blocks"
        " (template_id, start_min, end_min, name, category, sort_order)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(tid, s, e, n, c, i) for i, (s, e, n, c) in enumerate(WORKDAY_BLOCKS)],
    )
    conn.commit()
    return tid
