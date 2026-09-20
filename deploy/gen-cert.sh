#!/usr/bin/env bash
#
# 生成自签证书（无域名场景）。
#
# 要点：现代浏览器只认 SAN（subjectAltName），CN 字段早已被忽略。
# 只填 CN=IP 会导致浏览器报「证书名称无效」，必须用 -addext 写 SAN。
#
# 用法：
#   sudo ./gen-cert.sh 1.2.3.4          # 换成你的公网 IP
#   sudo ./gen-cert.sh 1.2.3.4 10.0.0.5 # 可附内网 IP，便于局域网也免告警
#
set -euo pipefail

IP="${1:-}"
if [[ -z "$IP" ]]; then
  echo "用法: sudo $0 <公网IP> [额外IP...]" >&2
  exit 1
fi

SSL_DIR=/etc/nginx/ssl
DAYS=3650
CRT="$SSL_DIR/timeline-trace.crt"
KEY="$SSL_DIR/timeline-trace.key"

# 拼 SAN：公网 IP 必填，其余参数一并加入
SAN="IP:$IP"
for extra in "${@:2}"; do
  SAN="$SAN,IP:$extra"
done
# 顺带加上本机回环，方便本机 curl 不报警
SAN="$SAN,IP:127.0.0.1,DNS:localhost"

mkdir -p "$SSL_DIR"

if [[ -f "$CRT" ]]; then
  echo "已存在 $CRT，先备份为 .bak.$(date +%Y%m%d%H%M%S)"
  mv "$CRT" "$CRT.bak.$(date +%Y%m%d%H%M%S)"
  [[ -f "$KEY" ]] && mv "$KEY" "$KEY.bak.$(date +%Y%m%d%H%M%S)"
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$KEY" -out "$CRT" \
  -days "$DAYS" \
  -subj "/C=CN/O=timeline-trace/CN=$IP" \
  -addext "subjectAltName=$SAN" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"

chmod 600 "$KEY"
chmod 644 "$CRT"
chown root:root "$KEY" "$CRT" 2>/dev/null || true

echo
echo "证书已生成："
echo "  证书: $CRT"
echo "  私钥: $KEY"
echo "  SAN : $SAN"
echo
echo "校验 SAN 是否写进去了（应有 DNS/IP 段）："
openssl x509 -in "$CRT" -noout -text | grep -A1 "Subject Alternative Name"
echo
echo "记得 nginx -t && systemctl reload nginx"
