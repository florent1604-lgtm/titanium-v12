"""data/binance_ws.py — WebSocket aggTrade Binance avec failover et delta volume."""
from __future__ import annotations
import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Optional
import aiohttp
from utils.config import (
    SYMBOLS, WS_BASES, DELTA_VOL_ENABLED,
    DELTA_VOL_WINDOW, DELTA_VOL_SIGNAL_PCT, DELTA_VOL_USE_NOTIONAL,
)
from utils.logger import get_logger

logger = get_logger(__name__)

candle_store: Dict[str, "pd.DataFrame"] = {}
# Stocke des bougies 1-seconde agrégées (pas des trades bruts).
# maxlen=1800 = 30 min de données, quel que soit le volume de trades.
raw_1s: Dict[str, deque] = {s: deque(maxlen=1800) for s in SYMBOLS}

# Barre 1s en cours d'agrégation (non encore poussée dans raw_1s)
_current_1s: Dict[str, dict] = {}

delta_vol: Dict[str, dict] = {
    s: {
        "buy_vol": 0.0, "sell_vol": 0.0, "delta": 0.0,
        "delta_pct": 0.0, "bullish": False, "bearish": False,
        "trades": deque(maxlen=DELTA_VOL_WINDOW), "ts": 0.0,
    }
    for s in SYMBOLS
}

_BINANCE_SYM = {s: s.replace("/", "").lower() for s in SYMBOLS}


def _update_delta_vol(sym: str, price: float, qty: float, is_buyer_maker: bool) -> None:
    """Met à jour le delta volume.

    Pondération par notionnel (price × qty) quand DELTA_VOL_USE_NOTIONAL=1 :
    évite que le nombre de petites transactions domine face à une grosse transaction.
    """
    if not DELTA_VOL_ENABLED:
        return
    state    = delta_vol[sym]
    now      = datetime.now(timezone.utc).timestamp()
    notional = price * qty if DELTA_VOL_USE_NOTIONAL else qty
    trade    = {"ts": now, "qty": qty, "notional": notional, "side": "sell" if is_buyer_maker else "buy"}
    state["trades"].append(trade)

    vol_key  = "notional" if DELTA_VOL_USE_NOTIONAL else "qty"
    buy_vol  = sum(t[vol_key] for t in state["trades"] if t["side"] == "buy")
    sell_vol = sum(t[vol_key] for t in state["trades"] if t["side"] == "sell")
    total    = buy_vol + sell_vol or 1e-9

    state["buy_vol"]   = buy_vol
    state["sell_vol"]  = sell_vol
    state["delta"]     = buy_vol - sell_vol
    state["delta_pct"] = round((buy_vol - sell_vol) / total, 4)
    state["bullish"]   = (buy_vol / total) >= DELTA_VOL_SIGNAL_PCT
    state["bearish"]   = (sell_vol / total) >= DELTA_VOL_SIGNAL_PCT
    state["ts"]        = now


def _resample_1s_to_30s(sym: str) -> None:
    import pandas as pd
    buf = list(raw_1s[sym])
    if len(buf) < 2:
        return
    try:
        df_raw = pd.DataFrame(buf)
        df_raw["ts"] = pd.to_datetime(df_raw["ts"], unit="s", utc=True)
        df_raw = df_raw.set_index("ts").sort_index()
        # Agrégation 30s depuis les barres 1s — on dispose déjà de open/high/low/close/qty
        df30 = pd.DataFrame({
            "open":  df_raw["open"].resample("30s").first(),
            "high":  df_raw["high"].resample("30s").max(),
            "low":   df_raw["low"].resample("30s").min(),
            "close": df_raw["price"].resample("30s").last(),
            "v":     df_raw["qty"].resample("30s").sum(),
        }).dropna(subset=["open"])
        candle_store[sym] = df30.tail(500)
    except Exception as e:
        logger.warning("[WS] resample %s: %s", sym, e)


def _push_1s_bar(sym: str, ts_sec: int) -> None:
    """Pousse la barre 1s courante dans raw_1s et démarre une nouvelle barre."""
    bar = _current_1s.pop(sym, None)
    if bar:
        raw_1s[sym].append(bar)
        _resample_1s_to_30s(sym)


async def _handle_agg_trade(sym: str, msg: dict) -> None:
    try:
        price = float(msg["p"])
        qty   = float(msg["q"])
        ts    = float(msg["T"]) / 1000.0
        ts_sec = int(ts)
        is_buyer_maker = bool(msg["m"])

        # Agrégation en bougies 1s — évite que BTC (très haute fréquence) ne
        # remplisse raw_1s en quelques secondes avec tous les trades dans la même
        # fenêtre 30s (ce qui donnait < MIN_DF30_FOR_SCAN candles après resample).
        if sym not in _current_1s:
            _current_1s[sym] = {
                "ts": ts_sec, "price": price, "qty": qty,
                "open": price, "high": price, "low": price,
            }
        elif _current_1s[sym]["ts"] != ts_sec:
            # Nouvelle seconde — flush la barre précédente
            _push_1s_bar(sym, ts_sec)
            _current_1s[sym] = {
                "ts": ts_sec, "price": price, "qty": qty,
                "open": price, "high": price, "low": price,
            }
        else:
            bar = _current_1s[sym]
            bar["high"]  = max(bar["high"], price)
            bar["low"]   = min(bar["low"],  price)
            bar["price"] = price   # close = dernier prix
            bar["qty"]  += qty

        _update_delta_vol(sym, price, qty, is_buyer_maker)
    except Exception as e:
        logger.debug("[WS] handle_agg_trade %s: %s", sym, e)


async def seed_candle_store(session: aiohttp.ClientSession) -> None:
    """Amorce raw_1s avec l'historique REST 1m au démarrage.

    Sans ce seed, candle_store part de zéro à chaque lancement et le scan
    reste bloqué sur "df30 insuffisant" jusqu'à accumuler MIN_DF30_FOR_SCAN
    bougies 30s depuis le flux live — plusieurs minutes pour BTC, bien pire
    pour PAXG (trades rares). Chaque bougie 1m est convertie en 2 barres
    synthétiques placées dans des fenêtres 30s consécutives, puis le
    pipeline de resample existant reconstruit candle_store normalement.
    """
    from data.binance_rest import fetch_klines
    for sym in SYMBOLS:
        try:
            df1m = await fetch_klines(session, sym, "1m", limit=30)
        except Exception as e:
            logger.warning("[SEED] %s — backfill REST impossible (%s), le scan attendra le flux WS", sym, e)
            continue
        if df1m is None or df1m.empty:
            logger.warning("[SEED] %s — aucune bougie 1m reçue, le scan attendra le flux WS", sym)
            continue
        for ts, row in df1m.iterrows():
            base = int(ts.timestamp())
            half_qty = float(row["v"]) / 2.0
            for offset in (0, 30):
                raw_1s[sym].append({
                    "ts":    base + offset,
                    "open":  float(row["open"]),
                    "high":  float(row["high"]),
                    "low":   float(row["low"]),
                    "price": float(row["close"]),
                    "qty":   half_qty,
                })
        _resample_1s_to_30s(sym)
        n = len(candle_store.get(sym, []))
        logger.info("[SEED] %s — %d bougies 30s amorcées depuis REST 1m, scan prêt immédiatement", sym, n)


async def ws_binance(sym: str) -> None:
    stream = f"{_BINANCE_SYM[sym]}@aggTrade"
    ws_idx = 0

    while True:
        base = WS_BASES[ws_idx % len(WS_BASES)]
        url  = f"{base}/ws/{stream}"
        try:
            connector = aiohttp.TCPConnector(limit=10)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.ws_connect(url, heartbeat=20, timeout=aiohttp.ClientWSTimeout(ws_receive=60)) as ws:
                    logger.info("[WS] Connecté %s @ %s", sym, base)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            await _handle_agg_trade(sym, data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            logger.warning("[WS] %s déconnecté", sym)
                            break
        except Exception as e:
            logger.warning("[WS] %s erreur (%s): %s — retry dans 3s", sym, base, e)
            ws_idx += 1
            await asyncio.sleep(3)
