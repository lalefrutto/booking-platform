import os
import random
import uuid

# Доля отказов мок-эквайринга. По умолчанию 10% (успех — 90% случаев), но
# значение вынесено в переменную окружения PAYMENT_FAILURE_RATE, чтобы на защите
# можно было детерминированно показать обе ветки саги: 0 — только успех,
# 1 — гарантированный payment.failed.
FAILURE_RATE = float(os.getenv("PAYMENT_FAILURE_RATE", "0.1"))


def charge(amount: str) -> dict:
    """
    Имитация вызова внешнего платёжного шлюза (System_Ext на C4 L1).
    В реальной системе здесь был бы HTTPS-вызов к эквайеру (Stripe/YooKassa/etc).
    """
    if random.random() >= FAILURE_RATE:
        return {"success": True, "provider_ref": f"mock_txn_{uuid.uuid4().hex[:12]}"}
    return {"success": False, "reason": "insufficient_funds_or_declined_by_issuer"}
