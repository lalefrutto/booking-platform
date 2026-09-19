import logging

logger = logging.getLogger("notification-service.sender")


def send(channel: str, recipient_hint: str, message: str) -> bool:
    """
    Имитация отправки через внешнего провайдера (System_Ext на C4 L1).
    В реальной системе — интеграция с SMTP/SMS-агрегатором.
    """
    logger.info("[MOCK %s -> %s] %s", channel.upper(), recipient_hint, message)
    return True
