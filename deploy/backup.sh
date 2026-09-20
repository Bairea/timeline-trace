#!/usr/bin/env bash
#
# SQLite 备份。用 sqlite3 的 .backup 而不是 cp——
# 数据库在 WAL 模式下运行时直接 cp 可能拿到撕裂的快照。
#
# 用法：
#   ./backup.sh                  # 备份到 ../backups/
#   BACKUP_DIR=/mnt/x ./backup.sh
#
# 建议 cron（每天 03:00，并保留 60 天）：
#   0 3 * * * /opt/timeline-trace/deploy/backup.sh >> /var/log/tt-backup.log 2>&1
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$APP_DIR/data/timeline.db"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-60}"

if [[ ! -f "$DB" ]]; then
  echo "找不到数据库：$DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/timeline-$STAMP.db"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$OUT'"
else
  # 没装 sqlite3 时的退路：用 Python 标准库的备份 API
  # （它内部会加锁做一致性快照，比 cp 安全）
  python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY
fi

# 一致性自检：备份出来的库能读、表结构在
if ! sqlite3 "$OUT" "SELECT count(*) FROM actual_blocks;" >/dev/null 2>&1; then
  if ! python3 -c "
import sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.execute('SELECT count(*) FROM actual_blocks'); c.close()
" "$OUT" 2>/dev/null; then
    echo "备份校验失败，保留文件以便排查：$OUT" >&2
    exit 1
  fi
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "$(date '+%F %T') 备份完成：$OUT ($SIZE)"

# 清理超期备份
DELETED=$(find "$BACKUP_DIR" -name 'timeline-*.db' -type f -mtime "+$KEEP_DAYS" -print -delete | wc -l)
[[ "$DELETED" -gt 0 ]] && echo "已清理 $DELETED 个超过 $KEEP_DAYS 天的备份"
