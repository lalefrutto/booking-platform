variable "namespace" {
  type = string
}

variable "postgres_user" {
  type    = string
  default = "postgres"
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "registry_server" {
  description = "In-cluster registry из Части 5 (Kaniko пушит туда образы)"
  type        = string
  default     = "registry.localhost:5000"
}

# Учётные данные БД. Helm-чарты сервисов ссылаются на этот Secret через
# secretKeyRef — в values.yaml пароли открытым текстом не попадают.
resource "kubernetes_secret" "postgres" {
  metadata {
    name      = "postgres-credentials"
    namespace = var.namespace
  }

  data = {
    POSTGRES_USER     = var.postgres_user
    POSTGRES_PASSWORD = var.postgres_password
  }

  type = "Opaque"
}

# Секрет подписи JWT для user-service.
resource "kubernetes_secret" "jwt" {
  metadata {
    name      = "jwt-secret"
    namespace = var.namespace
  }

  data = {
    JWT_SECRET = var.jwt_secret
  }

  type = "Opaque"
}

# Pull-secret для in-cluster registry. Реестр в k3d работает без
# аутентификации, но secret заводится заранее: так манифесты сервисов
# одинаковы для локального стенда и для реестра с авторизацией в проде.
resource "kubernetes_secret" "registry" {
  metadata {
    name      = "registry-pull-secret"
    namespace = var.namespace
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = jsonencode({
      auths = {
        (var.registry_server) = {
          auth = base64encode("anonymous:anonymous")
        }
      }
    })
  }
}

output "postgres_secret_name" {
  value = kubernetes_secret.postgres.metadata[0].name
}

output "jwt_secret_name" {
  value = kubernetes_secret.jwt.metadata[0].name
}

output "registry_secret_name" {
  value = kubernetes_secret.registry.metadata[0].name
}
