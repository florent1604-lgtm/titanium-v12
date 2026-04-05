"""data/binance_rest.py — Klines Binance REST avec cache TTL et fallback."""
from __future__ import annotations
import asyncio
from typing import Dict, Optional
import pandas as pd
import aiohttp
from utils.config import (
    REST_BASE, REST_FALLBACK, BINANCE_KEY,
    CACHE_TTL, KLINES_LIMIT,
)
from utils.cache import TTLCache
from utils.logger import get_logger

logger = get_logger(__name__)
_cache = TTLCache()

_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
}


def _parse_klines(raw: list) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    rows = []
    for k in raw:
        try:
            rows.append({
                "ts":    pd.to_datetime(int(k[0]), unit="ms", utc=True),
                "open":  float(k[1]),
                "high":  float(k[2]),
                "low":   float(k[3]),
                "close": float(k[4]),
                "v":     float(k[5]),
            })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    return df[~df.index.duplicated(keep="last")]


async def fetch_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    tf: str,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch bougies Binance REST avec cache TTL et fallback endpoint."""
    cache_key = f"{symbol}:{tf}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    binance_sym = symbol.replace("/", "")
    interval    = _TF_MAP.get(tf, tf)
    n           = limit or KLINES_LIMIT.get(tf, 300)
    ttl         = CACHE_TTL.get(tf, 60)
    headers     = {"X-MBX-APIKEY": BINANCE_KEY} if BINANCE_KEY else {}
    params      = {"symbol": binance_sym, "interval": interval, "limit": str(n)}
    last_error  = None

    for base in (REST_BASE, REST_FALLBACK):
        try:
            url = f"{base}/api/v3/klines"
            async with session.get(
                url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.warning("[REST] %s %s/%s HTTP %s: %s", base, symbol, tf, r.status, body[:80])
                    last_error = f"HTTP {r.status}"
                    continue
                raw = await r.json(content_type=None)
                df = _parse_klines(raw)
                if df.empty:
                    logger.warning("[REST] %s/%s réponse vide", symbol, tf)
                    last_error = "empty response"
                    continue
                _cache.set(cache_key, df, ttl=ttl)
                logger.debug("[REST] %s/%s → %d bougies", symbol, tf, len(df))
                return df
        except Exception as e:
            logger.warning("[REST] %s/%s erreur: %s", symbol, tf, e)
            last_error = str(e)
            await asyncio.sleep(0.5)

    raise RuntimeError(f"fetch_klines {symbol}/{tf} échoué: {last_error}")


async def fetch_klines_history(
    session: aiohttp.ClientSession,
    symbol: str,
    tf: str,
    days: int,
) -> pd.DataFrame:
    """Fetch plusieurs pages de klines pour couvrir `days` jours d'historique."""
    tf_minutes = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15,
        "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
    }
    minutes_per_candle = tf_minutes.get(tf, 5)
    candles_needed = int(days * 1440 / minutes_per_candle)
    pages = (candles_needed // 1000) + 1
    all_dfs = []
    for _ in range(min(pages, 10)):
        try:
            df = await fetch_klines(session, symbol, tf, limit=1000)
            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            logger.warning("[REST] fetch_klines_history %s/%s: %s", symbol, tf, e)
        await asyncio.sleep(0.2)

    if not all_dfs:
        return pd.DataFrame()
    combined = pd.concat(all_dfs).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    from datetime import datetime, timezone, timedelta
    cutoff = pd.Timestamp(datetime.now(timezone.utc) - timedelta(days=days))
    return combined[combined.index >= cutoff]


def invalidate_cache(symbol: str = "", tf: str = "") -> None:
    if symbol and tf:
        _cache.delete(f"{symbol}:{tf}")
    else:
        _cache.clear()
