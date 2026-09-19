variable "namespace" {
  description = "Неймспейс, в котором живут микросервисы"
  type        = string
}

variable "services" {
  description = "Список микросервисов — на каждый заводится свой ServiceAccount"
  type        = list(string)
}

# Отдельный ServiceAccount на сервис: это и identity для Istio mTLS
# (SPIFFE-идентификатор строится из SA), и точка привязки минимальных прав.
resource "kubernetes_service_account" "service" {
  for_each = toset(var.services)

  metadata {
    name      = each.value
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/name"       = each.value
      "app.kubernetes.io/part-of"    = "booking-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  automount_service_account_token = true
}

# Микросервисам не нужен доступ к API Kubernetes для бизнес-логики.
# Даём только чтение собственных ConfigMap/Secret — принцип наименьших привилегий.
resource "kubernetes_role" "service_config_reader" {
  metadata {
    name      = "config-reader"
    namespace = var.namespace
  }

  rule {
    api_groups = [""]
    resources  = ["configmaps", "secrets"]
    verbs      = ["get", "list", "watch"]
  }
}

resource "kubernetes_role_binding" "service_config_reader" {
  for_each = toset(var.services)

  metadata {
    name      = "${each.value}-config-reader"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.service_config_reader.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.service[each.value].metadata[0].name
    namespace = var.namespace
  }
}

output "service_account_names" {
  value = [for sa in kubernetes_service_account.service : sa.metadata[0].name]
}
