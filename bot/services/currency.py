"""Fetch and cache exchange rates from open.er-api.com."""
import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/SGD"
CACHE_TTL_SECONDS = 3600  # 1 hour

_cache: dict = {}
_cache_timestamp: float = 0.0
_cache_lock = asyncio.Lock()


async def get_rates() -> Optional[dict[str, float]]:
    global _cache, _cache_timestamp

    now = time.monotonic()
    if _cache and (now - _cache_timestamp) < CACHE_TTL_SECONDS:
        return _cache

    async with _cache_lock:
        # Re-check inside the lock: another coroutine may have refreshed while we waited.
        now = time.monotonic()
        if _cache and (now - _cache_timestamp) < CACHE_TTL_SECONDS:
            return _cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(EXCHANGE_RATE_URL)
                resp.raise_for_status()
                data = resp.json()

            if data.get("result") != "success":
                logger.error("Exchange rate API returned non-success: %s", data)
                return None

            _cache = data["rates"]
            _cache_timestamp = now
            logger.info("Exchange rates refreshed")
            return _cache
        except Exception as exc:
            logger.error("Failed to fetch exchange rates: %s", exc)
            return None


async def convert_to_sgd(amount: float, currency: str) -> tuple[Optional[float], Optional[float]]:
    """Return (amount_sgd, exchange_rate) or (None, None) on failure.
    exchange_rate is units of foreign currency per 1 SGD.
    """
    currency = currency.upper()
    if currency == "SGD":
        return amount, 1.0

    rates = await get_rates()
    if rates is None:
        return None, None

    rate = rates.get(currency)
    if rate is None:
        logger.warning("Unknown currency: %s", currency)
        return None, None

    return round(amount / rate, 6), round(rate, 6)
