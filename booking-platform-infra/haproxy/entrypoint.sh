#!/bin/bash
# Поднимает HAProxy и Keepalived в одном контейнере.
set -euo pipefail

: "${KA_STATE:=BACKUP}"
: "${KA_PRIORITY:=100}"
: "${KA_VIP:=172.20.0.200}"
: "${KA_ROUTER_ID:=51}"
: "${KA_INTERFACE:=eth0}"

KA_UNICAST_SRC="$(ip -4 -o addr show dev "$KA_INTERFACE" | awk '{print $4}' | cut -d/ -f1)"

# envsubst подставляет ТОЛЬКО экспортированные переменные. HOSTNAME и значения,
# заданные через ":=" выше, — это переменные оболочки, поэтому без явного
# export шаблон рендерится с пустым `interface`, и keepalived падает с
# "Configuration line starting `interface` is missing a parameter".
export KA_STATE KA_PRIORITY KA_VIP KA_ROUTER_ID KA_INTERFACE KA_UNICAST_SRC KA_UNICAST_PEER
export HOSTNAME="${HOSTNAME:-$(hostname)}"

echo "[entrypoint] node=$HOSTNAME state=$KA_STATE priority=$KA_PRIORITY"
echo "[entrypoint] src=$KA_UNICAST_SRC peer=${KA_UNICAST_PEER:-<unset>} vip=$KA_VIP"

envsubst '${HOSTNAME} ${KA_STATE} ${KA_PRIORITY} ${KA_INTERFACE} ${KA_VIP} ${KA_ROUTER_ID} ${KA_UNICAST_SRC} ${KA_UNICAST_PEER}' \
  < /etc/keepalived/keepalived.conf.tmpl > /etc/keepalived/keepalived.conf

# При `docker start` файловая система контейнера сохраняется, и keepalived
# находит свой старый pid-файл от прошлого запуска: "daemon is already running",
# после чего VRRP не поднимается и узел никогда не возвращает себе VIP.
rm -f /var/run/keepalived*.pid /run/keepalived*.pid 2>/dev/null || true

echo "[entrypoint] запуск HAProxy"
haproxy -f /usr/local/etc/haproxy/haproxy.cfg -D

# Ждём, пока HAProxy начнёт отвечать, иначе vrrp_script сразу уронит приоритет.
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8404/ -o /dev/null; then break; fi
  sleep 1
done

echo "[entrypoint] запуск Keepalived (VRRP)"
exec keepalived -n -l -D -f /etc/keepalived/keepalived.conf
