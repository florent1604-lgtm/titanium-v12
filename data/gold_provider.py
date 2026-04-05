"""data/gold_provider.py — XAU/USD via Twelve Data (primaire) + Yahoo Finance (fallback)."""
from __future__ import annotations
import asyncio
from typing import Dict, Optional
import pandas as pd
import aiohttp
from utils.config import (
    TWELVEDATA_API_KEY, TWELVEDATA_BASE_URL, GOLD_REAL_ENABLED,
    GOLD_CACHE_TTL, GOLD_SYMBOL_MAP, TD_TF_MAP, YF_TF_MAP,
)
from utils.cache import TTLCache
from utils.logger import get_logger

logger = get_logger(__name__)
_cache = TTLCache()
gold_store: Dict[str, pd.DataFrame] = {}


def _parse_twelvedata(data: dict) -> pd.DataFrame:
    values = data.get("values", [])
    if not values:
        return pd.DataFrame()
    rows = []
    for v in values:
        try:
            rows.append({
                "ts":    pd.to_datetime(v["datetime"], utc=True),
                "open":  float(v["open"]),
                "high":  float(v["high"]),
                "low":   float(v["low"]),
                "close": float(v["close"]),
                "v":     float(v.get("volume", 0) or 0),
            })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    return df[~df.index.duplicated(keep="last")]


async def _fetch_twelvedata(session: aiohttp.ClientSession, interval: str, outputsize: int = 500) -> pd.DataFrame:
    if not TWELVEDATA_API_KEY:
        return pd.DataFrame()
    td_interval = TD_TF_MAP.get(interval, interval)
    params = {
        "symbol": "XAU/USD", "interval": td_interval,
        "outputsize": str(min(5000, max(1, outputsize))),
        "apikey": TWELVEDATA_API_KEY, "timezone": "UTC", "format": "JSON",
    }
    try:
        async with session.get(
            f"{TWELVEDATA_BASE_URL}/time_series", params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status != 200:
                body = await r.text()
                logger.warning("[GOLD/TD] HTTP %s: %s", r.status, body[:80])
                return pd.DataFrame()
            data = await r.json(content_type=None)
        if isinstance(data, dict) and data.get("code"):
            logger.warning("[GOLD/TD] Erreur API %s: %s", data.get("code"), data.get("message", "")[:80])
            return pd.DataFrame()
        df = _parse_twelvedata(data)
        if not df.empty:
            logger.info("[GOLD/TD] XAU/USD/%s → %d bougies", interval, len(df))
        return df
    except Exception as e:
        logger.warning("[GOLD/TD] fetch error %s: %s", interval, e)
        return pd.DataFrame()


async def _fetch_yahoo(session: aiohttp.ClientSession, interval: str, count: int = 500) -> pd.DataFrame:
    _yf_cfg = {
        "4h": ("1h", "60d"), "2h": ("1h", "60d"), "1h": ("1h", "60d"),
        "30m": ("30m", "30d"), "15m": ("15m", "10d"),
        "5m": ("5m", "5d"), "3m": ("5m", "5d"),
        "1m": ("1m", "7d"), "1d": ("1d", "730d"),
    }
    yf_interval, period = _yf_cfg.get(interval, ("1h", "30d"))
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        f"?interval={yf_interval}&range={period}&includeTimestamps=true"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20),
                               headers={"User-Agent": "Mozilla/5.0"}) as r:
            if r.status != 200:
                logger.warning("[GOLD/YF] HTTP %s", r.status)
                return pd.DataFrame()
            data = await r.json(content_type=None)
        result = data.get("chart", {}).get("result", [])
        if not result:
            return pd.DataFrame()
        res   = result[0]
        times = res.get("timestamp", [])
        ohlcv = res.get("indicators", {}).get("quote", [{}])[0]
        rows = []
        for i, ts in enumerate(times):
            try:
                rows.append({
                    "ts":    pd.to_datetime(ts, unit="s", utc=True),
                    "open":  float((ohlcv.get("open",  []) or [None])[i] or 0),
                    "high":  float((ohlcv.get("high",  []) or [None])[i] or 0),
                    "low":   float((ohlcv.get("low",   []) or [None])[i] or 0),
                    "close": float((ohlcv.get("close", []) or [None])[i] or 0),
                    "v":     float((ohlcv.get("volume",[]) or [None])[i] or 0),
                })
            except Exception:
                continue
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).set_index("ts").sort_index()
        df = df[(df["close"] > 0)]
        df = df[~df.index.duplicated(keep="last")]
        logger.info("[GOLD/YF] GC=F/%s → %d bougies", interval, len(df))
        return df
    except Exception as e:
        logger.warning("[GOLD/YF] fetch error %s: %s", interval, e)
        return pd.DataFrame()


async def fetch_gold_candles(session: aiohttp.ClientSession, interval: str = "4h") -> pd.DataFrame:
    """Fetch bougies XAU/USD — Twelve Data primaire, Yahoo Finance fallback."""
    if not GOLD_REAL_ENABLED:
        return pd.DataFrame()

    cache_key = f"gold:{interval}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    df = await _fetch_twelvedata(session, interval)
    if df.empty:
        logger.info("[GOLD] Twelve Data vide — fallback Yahoo Finance")
        df = await _fetch_yahoo(session, interval)

    if not df.empty:
        _cache.set(cache_key, df, ttl=GOLD_CACHE_TTL)
        gold_store[interval] = df

    return df


async def gold_refresh_loop(session: aiohttp.ClientSession) -> None:
    while True:
        for tf in ["4h", "1h", "30m", "15m", "5m", "1d"]:
            try:
                await fetch_gold_candles(session, tf)
            except Exception as e:
                logger.warning("[GOLD] refresh %s: %s", tf, e)
            await asyncio.sleep(1)
        await asyncio.sleep(180)
