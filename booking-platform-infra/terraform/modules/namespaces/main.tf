variable "namespaces" {
  description = "Неймспейсы кластера: имя -> метаданные (istio-injection, метки)"
  type = map(object({
    istio_injection = optional(bool, false)
    labels          = optional(map(string), {})
  }))
}

resource "kubernetes_namespace" "this" {
  for_each = var.namespaces

  metadata {
    name = each.key

    labels = merge(
      {
        "app.kubernetes.io/part-of"    = "booking-platform"
        "app.kubernetes.io/managed-by" = "terraform"
      },
      # Включает автоматическую инжекцию sidecar-прокси Istio (Часть 3).
      each.value.istio_injection ? { "istio-injection" = "enabled" } : {},
      each.value.labels
    )
  }
}

output "names" {
  value = [for ns in kubernetes_namespace.this : ns.metadata[0].name]
}
