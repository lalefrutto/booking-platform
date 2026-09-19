# HAProxy + Keepalived в одном образе.
#
# Пара таких контейнеров стоит ПЕРЕД Istio Ingress Gateway и держит плавающий
# VIP по протоколу VRRP: если активный узел падает, второй забирает адрес
# на себя. Это замена облачного L4-балансировщика для bare-metal/локального
# стенда.
FROM haproxy:2.9-alpine

USER root

# gettext — ради envsubst, которым entrypoint рендерит keepalived.conf
RUN apk add --no-cache keepalived iproute2 bash curl gettext

COPY haproxy.cfg /usr/local/etc/haproxy/haproxy.cfg
COPY keepalived.conf.tmpl /etc/keepalived/keepalived.conf.tmpl
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
