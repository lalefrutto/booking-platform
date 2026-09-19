#!/usr/bin/env bash
# Запускает playbook в контейнере-раннере Ansible.
#
# Зачем контейнер: управляющий узел Ansible должен быть POSIX-системой, а стенд
# работает на Windows. Контейнер подключается к docker-сети k3d, поэтому в
# kubeconfig адрес API-сервера подменяется на внутреннее имя балансировщика
# k3d (k3d-booking-serverlb:6443) вместо 0.0.0.0:<host-port>.
#
# Использование:  ./run.sh playbook-kafka.yml
set -euo pipefail

PLAYBOOK="${1:-playbook-kafka.yml}"
CLUSTER="${K3D_CLUSTER:-booking}"
NETWORK="k3d-${CLUSTER}"
IMAGE="booking-infra/ansible-runner:1.0"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Сборка образа раннера (если нужно)"
docker build -q -t "$IMAGE" "$HERE" > /dev/null

echo "==> Подготовка kubeconfig для доступа изнутри сети $NETWORK"
mkdir -p "$HERE/.kube"
k3d kubeconfig get "$CLUSTER" \
  | sed -E "s#server: https://[^ ]+#server: https://k3d-${CLUSTER}-serverlb:6443#" \
  > "$HERE/.kube/config"

echo "==> Запуск playbook: $PLAYBOOK"
MSYS_NO_PATHCONV=1 docker run --rm \
  --network "$NETWORK" \
  -v "$HERE:/ansible" \
  -e K8S_AUTH_KUBECONFIG=/ansible/.kube/config \
  "$IMAGE" \
  -i /ansible/inventory.ini \
  "/ansible/$PLAYBOOK"
