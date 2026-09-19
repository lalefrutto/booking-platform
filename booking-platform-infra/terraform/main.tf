##############################################################################
# Корневая конфигурация Terraform для Блока 2.
#
# Провайдеры — kubernetes и helm, без облачного провайдера: кластер локальный
# (k3d), поэтому Terraform отвечает не за создание нод, а за «день 0» внутри
# уже существующего кластера: неймспейсы, RBAC/ServiceAccounts, базовые секреты
# и установку ArgoCD, который дальше раскатывает всё остальное по GitOps.
#
# Применить:
#   terraform init
#   terraform apply -var="postgres_password=postgres" -var="jwt_secret=..."
##############################################################################

terraform {
  required_version = ">= 1.5"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
  }
}

variable "kube_context" {
  description = "Контекст kubeconfig, созданный k3d"
  type        = string
  default     = "k3d-booking"
}

variable "postgres_password" {
  type      = string
  sensitive = true
  default   = "postgres"
}

variable "jwt_secret" {
  type      = string
  sensitive = true
  default   = "change-me-in-production"
}

variable "app_namespace" {
  type    = string
  default = "booking"
}

provider "kubernetes" {
  config_path    = pathexpand("~/.kube/config")
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = pathexpand("~/.kube/config")
    config_context = var.kube_context
  }
}

##############################################################################
# Неймспейсы
##############################################################################

module "namespaces" {
  source = "./modules/namespaces"

  namespaces = {
    # Микросервисы Блока 1 — с инжекцией sidecar'ов Istio.
    (var.app_namespace) = {
      istio_injection = true
    }
    # Данные (PostgreSQL/MongoDB/Valkey) — БЕЗ инжекции sidecar'ов.
    # mTLS до БД был бы плюсом, но StatefulSet'ы с прокси добавляют отказов
    # на ровном месте (порядок старта, exec-пробы mongosh/pg_isready),
    # а телеметрию L7 по TCP-протоколам Postgres/Mongo Istio всё равно не даёт.
    "booking-data" = {
      istio_injection = false
    }
    # Strimzi-оператор и кластер Kafka (Часть 2, Ansible).
    # Без инжекции: брокеры Kafka работают по своему протоколу, sidecar
    # только мешал бы и ломал bootstrap-протокол.
    "kafka" = {
      istio_injection = false
    }
    "argocd"        = { istio_injection = false }
    "observability" = { istio_injection = false }
  }
}

##############################################################################
# RBAC: по ServiceAccount на каждый микросервис
##############################################################################

module "rbac" {
  source = "./modules/rbac"

  namespace = var.app_namespace
  services = [
    "user-service",
    "catalog-service",
    "booking-service",
    "payment-service",
    "notification-service",
    "review-service",
  ]

  depends_on = [module.namespaces]
}

##############################################################################
# Базовые секреты
##############################################################################

module "secrets_app" {
  source = "./modules/secrets"

  namespace         = var.app_namespace
  postgres_password = var.postgres_password
  jwt_secret        = var.jwt_secret

  depends_on = [module.namespaces]
}

module "secrets_data" {
  source = "./modules/secrets"

  namespace         = "booking-data"
  postgres_password = var.postgres_password
  jwt_secret        = var.jwt_secret

  depends_on = [module.namespaces]
}

##############################################################################
# ArgoCD — дальше всё разворачивается через него (App of Apps)
##############################################################################

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = "7.8.2"
  namespace  = "argocd"

  # LOCAL: одна реплика каждого компонента и выключенный Dex —
  # для стенда HA-раскладка ArgoCD не нужна и не помещается по памяти.
  values = [yamlencode({
    dex = { enabled = false }
    redis-ha = { enabled = false }
    controller = { replicas = 1 }
    server = {
      replicas = 1
      # insecure: ArgoCD за Istio Ingress, TLS терминируется выше.
      extraArgs = ["--insecure"]
    }
    repoServer = { replicas = 1 }
    applicationSet = { replicas = 1 }
    configs = {
      params = {
        "server.insecure" = true
      }
    }
  })]

  depends_on = [module.namespaces]
  timeout    = 900
}

output "namespaces_created" {
  value = module.namespaces.names
}

output "service_accounts" {
  value = module.rbac.service_account_names
}
