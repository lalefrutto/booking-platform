#!/bin/sh
# Сборка образа сервиса через Kaniko — без доступа к docker-сокету.
#
# Kaniko запускается как Job в кластере: он сам клонирует репозиторий по
# git-контексту, собирает слои в userspace и пушит результат в in-cluster
# registry. Ни привилегированный контейнер, ни docker.sock не нужны —
# ради этого Kaniko в плане Части 5 и выбран.
#
# Использование: ci/kaniko-build.sh <service-name> <tag>
set -eu

SERVICE="$1"
TAG="$2"

NAMESPACE="${KANIKO_NAMESPACE:-ci}"
REGISTRY="${REGISTRY:-registry.localhost:5000}"
IMAGE_PREFIX="${IMAGE_PREFIX:-booking}"
GIT_REPO="${GIT_CONTEXT_REPO:-http://gitea-http.ci.svc.cluster.local:3000/gitops/booking-platform.git}"
GIT_REF="${GIT_CONTEXT_REF:-refs/heads/main}"

JOB="kaniko-${SERVICE}-${TAG}"
JOB="$(echo "$JOB" | tr '.' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-63)"

echo "==> Kaniko: ${SERVICE}:${TAG} -> ${REGISTRY}/${IMAGE_PREFIX}/${SERVICE}:${TAG}"

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
            # Для git-контекста Kaniko по умолчанию ходит по HTTPS и падает с
            # "server gave HTTP response to HTTPS client": Gitea на стенде
            # слушает обычный HTTP.
            - name: GIT_PULL_METHOD
              value: http
          args:
            # Контекст берётся прямо из git — рабочая копия раннеру не нужна.
            - "--context=git://${GIT_REPO#http://}#${GIT_REF}"
            - "--context-sub-path=services/${SERVICE}"
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
