# Self-hosted runner GitHub Actions с предустановленным kubectl.
#
# kubectl вшит в образ намеренно: скачивать его на каждом запуске workflow
# по медленному каналу — это лишние ~50 МБ и несколько минут на шаг.
#
# Пользователь остаётся непривилегированным (runner), docker-сокет НЕ
# пробрасывается: сборка образов идёт через Kaniko-Job в кластере.
FROM ghcr.io/actions/actions-runner:2.321.0

ARG KUBECTL_VERSION=v1.31.5

USER root

RUN curl -sSLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod 0755 /usr/local/bin/kubectl \
    && kubectl version --client=true

USER runner
