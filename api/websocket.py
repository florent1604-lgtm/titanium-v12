"""api/websocket.py — Broadcast WebSocket (envoi uniquement si signal change)."""
from __future__ import annotations
import asyncio
import base64
import gzip
import json
from typing import Any, Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from utils.config import WS_COMPRESS, WS_COMPRESS_MIN_BYTES, WS_COMPRESS_TYPES
from utils.logger import get_logger

logger = get_logger(__name__)

# Clients connectés par symbole
_clients: Dict[str, Set[WebSocket]] = {}
_ws_lock = asyncio.Lock()

# Limite max de clients WS par symbole — évite la fuite mémoire/CPU
# quand le dashboard est ouvert dans plusieurs onglets
MAX_CLIENTS_PER_SYMBOL = 10


async def ws_connect(sym: str, ws: WebSocket) -> None:
    """Enregistre un nouveau client WebSocket (avec limite anti-fuite)."""
    await ws.accept()
    async with _ws_lock:
        if sym not in _clients:
            _clients[sym] = set()

        # Éjecter les clients les plus anciens si la limite est atteinte
        if len(_clients[sym]) >= MAX_CLIENTS_PER_SYMBOL:
            stale = list(_clients[sym])[:len(_clients[sym]) - MAX_CLIENTS_PER_SYMBOL + 1]
            for old_ws in stale:
                _clients[sym].discard(old_ws)
                try:
                    await old_ws.close(code=1008, reason="too many connections")
                except Exception:
                    pass
            logger.warning("[WS] %s — %d clients éjectés (limite %d)", sym, len(stale), MAX_CLIENTS_PER_SYMBOL)

        _clients[sym].add(ws)
    logger.info("[WS] Client connecté %s (total: %d)", sym, len(_clients.get(sym, set())))


async def ws_disconnect(sym: str, ws: WebSocket) -> None:
    """Désenregistre un client WebSocket."""
    async with _ws_lock:
        if sym in _clients:
            _clients[sym].discard(ws)
    logger.info("[WS] Client déconnecté %s (total: %d)", sym, len(_clients.get(sym, set())))


def _compress_payload(data: str, msg_type: str) -> str:
    """Compresse le payload si WS_COMPRESS=gzip_base64 et payload suffisamment grand."""
    if WS_COMPRESS != "gzip_base64":
        return data
    if msg_type not in WS_COMPRESS_TYPES:
        return data
    if len(data) < WS_COMPRESS_MIN_BYTES:
        return data
    compressed = base64.b64encode(gzip.compress(data.encode())).decode()
    return json.dumps({"_compressed": "gzip_base64", "data": compressed})


async def broadcast(sym: str, state: Dict[str, Any]) -> None:
    """Envoie l'état courant à tous les clients WS abonnés à ce symbole."""
    clients = list(_clients.get(sym, set()))
    if not clients:
        return

    raw   = json.dumps(state, default=str)
    msg   = _compress_payload(raw, "signal")
    dead  = []

    for ws in clients:
        try:
            await ws.send_text(msg)
        except (WebSocketDisconnect, Exception):
            dead.append(ws)

    if dead:
        async with _ws_lock:
            for ws in dead:
                _clients.get(sym, set()).discard(ws)


def get_client_count(sym: str = "") -> int:
    if sym:
        return len(_clients.get(sym, set()))
    return sum(len(v) for v in _clients.values())
