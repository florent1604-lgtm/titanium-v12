"""data/orderbook_ws.py — WebSocket L2 Order Book (Spot + Futures Binance).

Maintient un carnet d'ordres local en temps réel pour chaque symbole :
  - Spot : snapshot REST initial + diffs WebSocket @depth@100ms
  - Futures : snapshot REST initial + diffs WebSocket @depth@100ms
  - Historique des snapshots pour détection d'absorption
"""
from __future__ import annotations
import asyncio, json, time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from utils.config import (
    SYMBOLS, ORDERBOOK_L2_ENABLED, ORDERBOOK_SPOT_DEPTH,
    ORDERBOOK_FUTURES_DEPTH, ORDERBOOK_HISTORY_SIZE,
    ORDERBOOK_FUTURES_MAP, WS_BASES, FUTURES_BASE,
    REST_BASE, BINANCE_KEY,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OrderBookState:
    """État complet du carnet d'ordres L2 pour un symbole."""
    bids: List[List[float]] = field(default_factory=list)
    asks: List[List[float]] = field(default_factory=list)
    futures_bids: List[List[float]] = field(default_factory=list)
    futures_asks: List[List[float]] = field(default_factory=list)
    spread_bps: float = 0.0
    mid_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    last_update_id: int = 0
    futures_last_update_id: int = 0
    ts: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=ORDERBOOK_HISTORY_SIZE))

    def _compute_derived(self) -> None:
        src_bids = self.bids or self.futures_bids
        src_asks = self.asks or self.futures_asks
        if src_bids and src_asks:
            self.best_bid = src_bids[0][0]
            self.best_ask = src_asks[0][0]
            self.mid_price = (self.best_bid + self.best_ask) / 2.0
            if self.mid_price > 0:
                self.spread_bps = (self.best_ask - self.best_bid) / self.mid_price * 10000

    def push_history(self) -> None:
        self.history.append({
            "ts": time.time(),
            "bids": [list(b) for b in self.bids[:20]],
            "asks": [list(a) for a in self.asks[:20]],
            "f_bids": [list(b) for b in self.futures_bids[:20]],
            "f_asks": [list(a) for a in self.futures_asks[:20]],
        })

    def to_dict(self) -> dict:
        return {
            "best_bid": self.best_bid, "best_ask": self.best_ask,
            "mid_price": round(self.mid_price, 2),
            "spread_bps": round(self.spread_bps, 2),
            "spot_levels": len(self.bids), "futures_levels": len(self.futures_bids),
            "history_size": len(self.history), "ts": self.ts,
        }


orderbook_store: Dict[str, OrderBookState] = {s: OrderBookState() for s in SYMBOLS}
_BINANCE_SYM = {s: s.replace("/", "").lower() for s in SYMBOLS}


def _parse_depth(data: dict) -> Tuple[List[List[float]], List[List[float]], int]:
    bids = [[float(b[0]), float(b[1])] for b in data.get("bids", [])]
    asks = [[float(a[0]), float(a[1])] for a in data.get("asks", [])]
    return bids, asks, int(data.get("lastUpdateId", 0))


async def _fetch_spot_snapshot(session, sym):
    headers = {"X-MBX-APIKEY": BINANCE_KEY} if BINANCE_KEY else {}
    try:
        url = f"{REST_BASE}/api/v3/depth"
        params = {"symbol": sym.replace("/", ""), "limit": str(ORDERBOOK_SPOT_DEPTH)}
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return _parse_depth(await r.json(content_type=None))
            logger.warning("[ORDERBOOK] Spot snapshot %s HTTP %s", sym, r.status)
    except Exception as e:
        logger.warning("[ORDERBOOK] Spot snapshot %s: %s", sym, e)
    return [], [], 0


async def _fetch_futures_snapshot(session, sym):
    fsym = ORDERBOOK_FUTURES_MAP.get(sym)
    if not fsym:
        return [], [], 0
    headers = {"X-MBX-APIKEY": BINANCE_KEY} if BINANCE_KEY else {}
    try:
        url = f"{FUTURES_BASE}/fapi/v1/depth"
        params = {"symbol": fsym, "limit": str(min(ORDERBOOK_FUTURES_DEPTH, 1000))}
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return _parse_depth(await r.json(content_type=None))
            logger.warning("[ORDERBOOK] Futures snapshot %s HTTP %s", sym, r.status)
    except Exception as e:
        logger.warning("[ORDERBOOK] Futures snapshot %s: %s", sym, e)
    return [], [], 0


def _apply_depth_update(current, updates, is_bids):
    """Applique les diffs incrémentiels au carnet local."""
    book = {lvl[0]: lvl[1] for lvl in current}
    for u in updates:
        price, qty = float(u[0]), float(u[1])
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty
    result = [[p, q] for p, q in book.items()]
    result.sort(key=lambda x: x[0], reverse=is_bids)
    return result


async def _ws_spot_depth(sym):
    if not ORDERBOOK_L2_ENABLED:
        return
    stream = f"{_BINANCE_SYM[sym]}@depth@100ms"
    ws_idx = 0
    while True:
        base = WS_BASES[ws_idx % len(WS_BASES)]
        url = f"{base}/ws/{stream}"
        try:
            conn = aiohttp.TCPConnector(limit=5)
            async with aiohttp.ClientSession(connector=conn) as session:
                bids, asks, lid = await _fetch_spot_snapshot(session, sym)
                state = orderbook_store[sym]
                state.bids, state.asks, state.last_update_id = bids, asks, lid
                state._compute_derived()
                state.ts = time.time()
                logger.info("[ORDERBOOK] Spot snapshot %s — %d bids, %d asks", sym, len(bids), len(asks))
                async with session.ws_connect(url, heartbeat=20,
                                              timeout=aiohttp.ClientWSTimeout(ws_receive=60)) as ws:
                    logger.info("[ORDERBOOK] WS spot connecté %s", sym)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            fid = data.get("u", 0)
                            if fid <= state.last_update_id:
                                continue
                            state.bids = _apply_depth_update(state.bids, data.get("b", []), True)
                            state.asks = _apply_depth_update(state.asks, data.get("a", []), False)
                            state.last_update_id = fid
                            state._compute_derived()
                            state.ts = time.time()
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
        except Exception as e:
            logger.warning("[ORDERBOOK] WS spot %s erreur: %s — retry 5s", sym, e)
            ws_idx += 1
            await asyncio.sleep(5)


async def _ws_futures_depth(sym):
    if not ORDERBOOK_L2_ENABLED:
        return
    fsym = ORDERBOOK_FUTURES_MAP.get(sym)
    if not fsym:
        return
    stream = f"{fsym.lower()}@depth@100ms"
    while True:
        url = f"wss://fstream.binance.com/ws/{stream}"
        try:
            conn = aiohttp.TCPConnector(limit=5)
            async with aiohttp.ClientSession(connector=conn) as session:
                bids, asks, lid = await _fetch_futures_snapshot(session, sym)
                state = orderbook_store[sym]
                state.futures_bids, state.futures_asks = bids, asks
                state.futures_last_update_id = lid
                state._compute_derived()
                state.push_history()
                logger.info("[ORDERBOOK] Futures snapshot %s — %d bids, %d asks", sym, len(bids), len(asks))
                async with session.ws_connect(url, heartbeat=20,
                                              timeout=aiohttp.ClientWSTimeout(ws_receive=60)) as ws:
                    logger.info("[ORDERBOOK] WS futures connecté %s", sym)
                    snap_ctr = 0
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            fid = data.get("u", 0)
                            if fid <= state.futures_last_update_id:
                                continue
                            state.futures_bids = _apply_depth_update(state.futures_bids, data.get("b", []), True)
                            state.futures_asks = _apply_depth_update(state.futures_asks, data.get("a", []), False)
                            state.futures_last_update_id = fid
                            state._compute_derived()
                            state.ts = time.time()
                            snap_ctr += 1
                            if snap_ctr >= 30:
                                state.push_history()
                                snap_ctr = 0
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
        except Exception as e:
            logger.warning("[ORDERBOOK] WS futures %s erreur: %s — retry 5s", sym, e)
            await asyncio.sleep(5)


async def _rest_polling_loop(sym):
    """Fallback REST polling si WS indisponible."""
    if not ORDERBOOK_L2_ENABLED:
        return
    await asyncio.sleep(30)
    while True:
        state = orderbook_store[sym]
        if time.time() - state.ts < 10:
            await asyncio.sleep(5)
            continue
        try:
            conn = aiohttp.TCPConnector(limit=5)
            async with aiohttp.ClientSession(connector=conn) as session:
                b, a, lid = await _fetch_spot_snapshot(session, sym)
                if b:
                    state.bids, state.asks, state.last_update_id = b, a, lid
                fb, fa, flid = await _fetch_futures_snapshot(session, sym)
                if fb:
                    state.futures_bids, state.futures_asks = fb, fa
                    state.futures_last_update_id = flid
                state._compute_derived()
                state.ts = time.time()
                state.push_history()
        except Exception as e:
            logger.debug("[ORDERBOOK] REST fallback %s: %s", sym, e)
        await asyncio.sleep(5)


async def start_orderbook_streams() -> None:
    """Lance les WebSocket L2 pour tous les symboles."""
    if not ORDERBOOK_L2_ENABLED:
        logger.info("[ORDERBOOK] L2 désactivé")
        return
    for sym in SYMBOLS:
        asyncio.create_task(_ws_spot_depth(sym))
        if sym in ORDERBOOK_FUTURES_MAP:
            asyncio.create_task(_ws_futures_depth(sym))
        asyncio.create_task(_rest_polling_loop(sym))
    logger.info("[ORDERBOOK] Streams L2 lancés pour %d symboles", len(SYMBOLS))


def get_orderbook(sym: str) -> Optional[OrderBookState]:
    state = orderbook_store.get(sym)
    return state if state and state.ts > 0 else None
