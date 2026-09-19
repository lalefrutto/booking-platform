import os
import httpx

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8000")


class CatalogUnavailableError(Exception):
    pass


class RoomNotFoundError(Exception):
    pass


def check_availability(room_id: str, check_in: str, check_out: str) -> dict:
    """Синхронный вызов Catalog Service для проверки доступности и получения цены."""
    try:
        resp = httpx.get(
            f"{CATALOG_SERVICE_URL}/rooms/{room_id}/availability",
            params={"check_in": check_in, "check_out": check_out},
            timeout=5.0,
        )
    except httpx.RequestError as exc:
        raise CatalogUnavailableError(str(exc)) from exc

    if resp.status_code == 404:
        raise RoomNotFoundError(f"Room {room_id} not found")
    resp.raise_for_status()
    return resp.json()
