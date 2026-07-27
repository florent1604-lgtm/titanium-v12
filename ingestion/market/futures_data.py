"""data/futures_data.py — Open Interest, Funding Rate, Mark Price (Binance Futures)."""
from __future__ import annotations
import asyncio
import time
from typing import Dict, Tuple
import aiohttp
from utils.config import (
    FUTURES_BASE, FUTURES_ENABLED, FUTURES_CACHE_TTL,
    FUTURES_SYMBOLS_MAP, BINANCE_KEY,
)
from utils.logger import get_logger

logger = get_logger(__name__)
futures_store: Dict[str, dict] = {}
_cache: Dict[str, Tuple[float, dict]] = {}


async def fetch_futures(session: aiohttp.ClientSession, sym: str) -> dict:
    if not FUTURES_ENABLED or sym not in FUTURES_SYMBOLS_MAP:
        return {}

    now = time.monotonic()
    if sym in _cache:
        ts, data = _cache[sym]
        if now - ts < FUTURES_CACHE_TTL:
            return data

    fsym    = FUTURES_SYMBOLS_MAP[sym]
    headers = {"X-MBX-APIKEY": BINANCE_KEY} if BINANCE_KEY else {}
    result  = {"symbol": sym, "fsym": fsym, "ok": False,
                "oi": 0.0, "oi_change_pct": 0.0,
                "funding": 0.0, "mark_price": 0.0, "long_short_ratio": 1.0}

    try:
        async with session.get(
            f"{FUTURES_BASE}/fapi/v1/openInterest",
            params={"symbol": fsym}, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 200:
                d = await r.json(content_type=None)
                result["oi"] = float(d.get("openInterest", 0.0) or 0.0)

        async with session.get(
            f"{FUTURES_BASE}/fapi/v1/premiumIndex",
            params={"symbol": fsym}, headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 200:
                d = await r.json(content_type=None)
                result["funding"]    = float(d.get("lastFundingRate", 0.0) or 0.0)
                result["mark_price"] = float(d.get("markPrice", 0.0) or 0.0)

        async with session.get(
            f"{FUTURES_BASE}/futures/data/globalLongShortAccountRatio",
            params={"symbol": fsym, "period": "5m", "limit": "1"},
            headers=headers, timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 200:
                ls = await r.json(content_type=None)
                if isinstance(ls, list) and ls:
                    result["long_short_ratio"] = float(ls[0].get("longShortRatio", 1.0) or 1.0)

        result["ok"] = True
        logger.debug("[FUTURES] %s OI=%.0f funding=%.6f", sym, result["oi"], result["funding"])

    except Exception as e:
        logger.debug("[FUTURES] %s erreur: %s", sym, e)
        result["error"] = str(e)[:80]

    _cache[sym] = (now, result)
    futures_store[sym] = result
    return result


async def futures_refresh_loop(session: aiohttp.ClientSession, symbols: list) -> None:
    while True:
        for sym in symbols:
            try:
                await fetch_futures(session, sym)
            except Exception as e:
                logger.warning("[FUTURES] refresh %s: %s", sym, e)
            await asyncio.sleep(1)
        await asyncio.sleep(FUTURES_CACHE_TTL)
