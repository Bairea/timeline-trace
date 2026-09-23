# 部署说明

目标：一台有公网 IP、**没有域名**的 Linux 服务器，单人自用。

架构：`nginx (443 自签 TLS) → uvicorn (127.0.0.1:8000) → 单 SQLite 文件`

---

## 0. 前置说明（先看这三条）

**① 浏览器一定会报证书告警。** 没有域名就签不出受信任的证书，这是必然而非配置失误。首次访问点「高级 → 继续前往」即可，之后不再提示。

**② 会话存在进程内存里，重启后要重新登录。** `app/auth.py` 用进程内 `set` 存会话 token，`systemctl restart` 会让所有已登录状态失效。单人自用可以接受；若嫌烦，把会话表落库即可（改 `auth.py` 三处）。

**③ uvicorn 只监听回环地址。** 公网流量一律经 nginx，不要图省事把 uvicorn 绑到 `0.0.0.0`——那样会绕过 nginx 的限流和 TLS。

---

## 1. 建用户与目录

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin timeline
sudo mkdir -p /opt/timeline-trace
sudo chown timeline:timeline /opt/timeline-trace
```

把代码同步到 `/opt/timeline-trace`（git clone 或 rsync 均可）。

## 2. Python 环境

依赖由 uv 管理（`pyproject.toml` + `uv.lock`）。按锁文件同步：`--no-dev` 跳过 pytest/httpx，`--frozen` 严格按锁文件装、不尝试更新。

```bash
# 装 uv（一次性；旧版系统 pip 无 PEP 668 限制，若报 externally-managed 再改用官方安装脚本）
sudo python3 -m pip install uv

cd /opt/timeline-trace
sudo -u timeline uv sync --frozen --no-dev
```

> `.venv` 位置不变（`/opt/timeline-trace/.venv`），systemd 单元的 `ExecStart` 路径无需改动。
> 系统自带 Python 低于 3.11 时，uv 会自动下载一个匹配的 Python，不用手动装。

## 3. 口令

```bash
sudo tee /etc/timeline-trace.env >/dev/null <<'EOF'
APP_PASSWORD=换成一个足够长的口令
# 走 HTTPS 时置 1，让 Cookie 带 Secure 标记
APP_COOKIE_SECURE=1
EOF
sudo chmod 600 /etc/timeline-trace.env
sudo chown root:root /etc/timeline-trace.env
```

> 口令泄漏等于数据泄漏。用 `openssl rand -base64 24` 生成一个，别用生日。

`data/` 目录需可写（服务以 `timeline` 身份运行）：

```bash
sudo -u timeline mkdir -p /opt/timeline-trace/data
```

## 4. systemd

```bash
sudo cp deploy/timeline-trace.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now timeline-trace
sudo systemctl status timeline-trace
journalctl -u timeline-trace -f        # 看日志
```

自检（应返回 `{"ok":true,...}`）：

```bash
curl -s http://127.0.0.1:8000/api/health
```

## 5. 证书

```bash
sudo ./deploy/gen-cert.sh <你的公网IP>
```

脚本会把 IP 写进 **SAN**（现代浏览器只看 SAN，不看 CN，这一步不能省）。

验证 SAN 确实生效：

```bash
openssl x509 -in /etc/nginx/ssl/timeline-trace.crt -noout -text \
  | grep -A1 "Subject Alternative Name"
```

## 6. nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/timeline-trace.conf
sudo nginx -t && sudo systemctl reload nginx
```

**防火墙**（只放行 22 / 80 / 443）：

```bash
sudo ufw allow 22,80,443/tcp
sudo ufw enable
```

## 7. 备份

```bash
chmod +x deploy/backup.sh
sudo crontab -e
# 加一行：
0 3 * * * /opt/timeline-trace/deploy/backup.sh >> /var/log/tt-backup.log 2>&1
```

脚本用 `sqlite3 .backup`（而非 `cp`）做一致性快照，并对产物做可读性校验；默认保留 60 天。

**恢复方法**：

```bash
sudo systemctl stop timeline-trace
cp backups/timeline-YYYYmmdd-HHMMSS.db /opt/timeline-trace/data/timeline.db
sudo chown timeline:timeline /opt/timeline-trace/data/timeline.db
sudo systemctl start timeline-trace
```

---

## 日常使用

- 记录：打开 `https://<IP>/`，底部输入框写 `20:30-21:10 干活` 回车。白天随手记即可。
- 对照：左栏是理想模板，右栏是实际。颜色表示对齐/偏移/未记录/计划外。
- 改块：拖动移动、拖上下边缘改时长、双击改名、悬停点 × 删除（5 秒内可撤销）。
- 统计：顶栏「统计」，可看任意区间的达标率与漏做分布。
- 导出：顶栏「导出 XLSX」，四个 sheet——**实际明细**（可直接求和）、**模板对照**、**日汇总**、**区间统计**。

> Excel 里对「实际明细」的 `duration_min` 直接 `SUM()` 是安全的，结果等于当日记录总时长。「模板对照」页**不要求和**：模板块之间本就有重叠和留白，加起来没有意义。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| 502 Bad Gateway | uvicorn 没起来。`systemctl status timeline-trace` 看状态 |
| 一直停在登录页 | 口令不对，或 `APP_PASSWORD` 没被读到。确认 EnvironmentFile 路径与权限 |
| 重启后要重新登录 | 预期行为，见前置说明 ② |
| 浏览器报证书名称无效 | SAN 没写对。重跑 `gen-cert.sh`，务必传入公网 IP |
| 时间块位置偏了 | 分钟→像素是 `0.75px/min`，24h = 1080px。页面缩放会改变观感，不影响数据 |
