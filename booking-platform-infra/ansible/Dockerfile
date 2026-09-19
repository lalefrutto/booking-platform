# Раннер Ansible.
#
# Ansible не работает нативно на Windows (управляющий узел должен быть
# POSIX), а в WSL здесь есть только служебный дистрибутив docker-desktop.
# Поэтому playbook'и запускаются из контейнера, подключённого к сети k3d.
# См. ansible/run.sh.
FROM python:3.12-slim

ARG HELM_VERSION=v3.16.3

RUN pip install --no-cache-dir \
        "ansible-core==2.17.6" \
        "kubernetes==31.0.0" \
        "PyYAML==6.0.2" \
        "jsonpatch==1.33"

# Модулю kubernetes.core.helm нужен бинарник helm в PATH.
ADD https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz /tmp/helm.tar.gz
RUN tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && rm -rf /tmp/helm.tar.gz /tmp/linux-amd64

RUN ansible-galaxy collection install kubernetes.core:==5.0.0

WORKDIR /ansible
# Коллбек вывода yaml живёт в коллекции ansible.posix, в базовом ansible-core
# его нет — оставляем стандартный, иначе playbook падает ещё до первой задачи.
ENV ANSIBLE_HOST_KEY_CHECKING=False \
    K8S_AUTH_KUBECONFIG=/ansible/.kube/config

ENTRYPOINT ["ansible-playbook"]
