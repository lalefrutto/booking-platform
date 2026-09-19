#!/bin/sh
# Сборка образа сервиса через Kaniko — без доступа к docker-сокету.
#
# Kaniko запускается как Job в кластере: он сам клонирует репозиторий по
# git-контексту, собирает слои в userspace и пушит результат в in-cluster
# registry. Ни привилегированный контейнер, ни docker.sock не нужны —
# ради этого Kaniko в плане Части 5 и выбран.
#
# Использование: ci/kaniko-build.sh <service-name> <tag>
#
# Переменные окружения:
#   GIT_CONTEXT_REPO    — URL репозитория с исходниками
#   GIT_CONTEXT_REF     — ref для сборки (по умолчанию refs/heads/main)
#   GIT_CONTEXT_SUBPATH — каталог сервиса внутри репозитория
#   GIT_TOKEN           — токен для клонирования приватного репозитория
#   REGISTRY, IMAGE_PREFIX, KANIKO_NAMESPACE
set -eu

SERVICE="$1"
TAG="$2"

NAMESPACE="${KANIKO_NAMESPACE:-ci}"
REGISTRY="${REGISTRY:-registry.localhost:5000}"
IMAGE_PREFIX="${IMAGE_PREFIX:-booking}"
GIT_REPO="${GIT_CONTEXT_REPO:-https://github.com/lalefrutto/booking-platform.git}"
GIT_REF="${GIT_CONTEXT_REF:-refs/heads/main}"
GIT_SUBPATH="${GIT_CONTEXT_SUBPATH:-booking-platform-prototype/services/${SERVICE}}"
GIT_TOKEN="${GIT_TOKEN:-}"

JOB="kaniko-${SERVICE}-${TAG}"
JOB="$(echo "$JOB" | tr '.' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-63)"

# Kaniko принимает git-контекст в виде git://<host>/<path>#<ref>.
CONTEXT_HOST_PATH="$(echo "$GIT_REPO" | sed -e 's|^https://||' -e 's|^http://||')"

# На github.com ходим по https, на in-cluster Gitea ходили по http:
# иначе Kaniko падал с "server gave HTTP response to HTTPS client".
case "$GIT_REPO" in
  http://*) PULL_METHOD=http ;;
  *)        PULL_METHOD=https ;;
esac

echo "==> Kaniko: ${SERVICE}:${TAG} -> ${REGISTRY}/${IMAGE_PREFIX}/${SERVICE}:${TAG}"
echo "    контекст: git://${CONTEXT_HOST_PATH}#${GIT_REF} (sub-path: ${GIT_SUBPATH})"

# Токен клонирования кладём в Secret, а не прямо в env Job'а: манифест Job'а
# виден всем, у кого есть get на batch/jobs. Secret живёт только на время
# сборки и удаляется в trap'е.
SECRET="${JOB}-git"
if [ -n "${GIT_TOKEN}" ]; then
  kubectl -n "${NAMESPACE}" create secret generic "${SECRET}" \
    --from-literal=GIT_TOKEN="${GIT_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  GIT_ENV="            - name: GIT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ${SECRET}
                  key: GIT_TOKEN"
else
  GIT_ENV=""
fi

cleanup() {
  if [ -n "${GIT_TOKEN}" ]; then
    kubectl -n "${NAMESPACE}" delete secret "${SECRET}" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB}
  namespace: ${NAMESPACE}
  labels:
    app: kaniko
    service: ${SERVICE}
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      labels:
        app: kaniko
    spec:
      restartPolicy: Never
      containers:
        - name: kaniko
          image: gcr.io/kaniko-project/executor:v1.23.2
          env:
            - name: GIT_PULL_METHOD
              value: ${PULL_METHOD}
${GIT_ENV}
          args:
            # Контекст берётся прямо из git — рабочая копия раннеру не нужна.
            - "--context=git://${CONTEXT_HOST_PATH}#${GIT_REF}"
            - "--context-sub-path=${GIT_SUBPATH}"
            - "--dockerfile=Dockerfile"
            - "--destination=${REGISTRY}/${IMAGE_PREFIX}/${SERVICE}:${TAG}"
            # Registry в k3d работает по HTTP без авторизации.
            - "--insecure"
            - "--skip-tls-verify"
            - "--cache=true"
            - "--cache-ttl=24h"
          resources:
            requests:
              cpu: 200m
              memory: 512Mi
            limits:
              memory: 2Gi
EOF

# Опрос вместо `kubectl wait` на два условия: в POSIX sh нет `wait -n`,
# а ждать только condition=complete нельзя — упавшая сборка висела бы
# до самого таймаута.
echo "==> Ожидание завершения Job ${JOB}"
i=0
while [ "$i" -lt 180 ]; do
  SUCCEEDED=$(kubectl -n "${NAMESPACE}" get "job/${JOB}" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "")
  FAILED=$(kubectl -n "${NAMESPACE}" get "job/${JOB}" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
  [ "${SUCCEEDED}" = "1" ] && break
  [ -n "${FAILED}" ] && [ "${FAILED}" != "0" ] && break
  i=$((i + 1))
  sleep 5
done

if [ "$(kubectl -n "${NAMESPACE}" get "job/${JOB}" -o jsonpath='{.status.succeeded}' 2>/dev/null)" = "1" ]; then
  echo "==> OK: ${SERVICE}:${TAG} собран и запушен"
  exit 0
fi

echo "==> ОШИБКА сборки ${SERVICE}:${TAG}, логи Kaniko:"
kubectl -n "${NAMESPACE}" logs "job/${JOB}" --tail=50 || true
exit 1
