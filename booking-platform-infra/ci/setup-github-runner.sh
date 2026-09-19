#!/usr/bin/env bash
# Разворачивает self-hosted runner GitHub Actions в кластере.
#
# Требует авторизованный gh CLI (скоупы repo + workflow):
#     gh auth status
#
# Использование: ci/setup-github-runner.sh [owner/repo]
set -euo pipefail

REPO="${1:-lalefrutto/booking-platform}"
NAMESPACE="${RUNNER_NAMESPACE:-ci}"
IMAGE="${RUNNER_IMAGE:-registry.localhost:5111/booking/github-runner:1.0.0}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Проверка авторизации gh"
gh auth status >/dev/null

echo "==> Сборка образа раннера (kubectl вшит внутрь)"
docker build -q -t "${IMAGE}" "${HERE}/github-runner" >/dev/null
docker push -q "${IMAGE}" >/dev/null
echo "    образ запушен: ${IMAGE}"

echo "==> Получение registration token для ${REPO}"
# Токен одноразовый и живёт около часа — в git он не попадает.
TOKEN="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq '.token')"
if [ -z "${TOKEN}" ]; then
  echo "Не удалось получить registration token" >&2
  exit 1
fi
echo "    токен получен (${#TOKEN} символов)"

kubectl -n "${NAMESPACE}" create secret generic github-runner-token \
  --from-literal=token="${TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Разворачивание раннера"
kubectl apply -f "${HERE}/github-runner.yaml"
# Секрет уже создан выше с настоящим токеном — возвращаем его на место,
# потому что манифест содержит PLACEHOLDER.
kubectl -n "${NAMESPACE}" create secret generic github-runner-token \
  --from-literal=token="${TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "${NAMESPACE}" rollout restart deploy/github-runner

echo "==> Ожидание готовности"
kubectl -n "${NAMESPACE}" rollout status deploy/github-runner --timeout=300s

echo "==> Зарегистрированные раннеры в ${REPO}:"
gh api "repos/${REPO}/actions/runners" \
  --jq '.runners[] | "    \(.name)  status=\(.status)  labels=\([.labels[].name] | join(","))"'
