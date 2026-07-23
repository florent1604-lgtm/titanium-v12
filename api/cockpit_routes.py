"""api/cockpit_routes.py — Endpoints du cockpit : spectral, guards, journal, events.

Endpoints :
  GET  /spectral/state       État spectral courant par symbole (Phase 1)
  GET  /guards               Config des guards actifs + derniers refus/passages
  GET  /journal              Journal de trades "Trading-as-Git" reconstruit (Phase J)
  POST /journal/{hash}/approve   Approuve un trade resté "staged" (JOURNAL_STAGING_ENABLED=1)
  GET  /events                Derniers événements typés du bus (Phase E)
  WS   /ws/events             Push temps réel des événements du bus
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from api.auth import require_admin

from utils.config import (
    GUARD_CORRELATED_EXPOSURE_ENABLED, GUARD_CORRELATED_EXPOSURE_MAX_PCT,
    GUARD_BLACKOUT_ENABLED, JOURNAL_STAGING_ENABLED, JOURNAL_AUTO_APPROVE,
)
from utils.logger import get_logger
from utils.event_bus import get_recent, subscribe, unsubscribe

logger = get_logger(__name__)
router = APIRouter(tags=["cockpit"])
_ADMIN = [Depends(require_admin)]


# ── GET /spectral/state ───────────────────────────────────────────────────────

@router.get("/spectral/state")
async def spectral_state():
    from core.signal_engine import get_spectral_state
    state = get_spectral_state()
    return JSONResponse({
        sym: feats.to_dict() if hasattr(feats, "to_dict") else feats
        for sym, feats in state.items()
    })


# ── GET /guards ────────────────────────────────────────────────────────────────

@router.get("/guards")
async def guards_status():
    return JSONResponse({
        "correlated_exposure": {
            "enabled":  GUARD_CORRELATED_EXPOSURE_ENABLED,
            "max_pct":  GUARD_CORRELATED_EXPOSURE_MAX_PCT,
        },
        "event_blackout": {"enabled": GUARD_BLACKOUT_ENABLED},
        "stop_loss_required": {"enabled": True},
        "symbol_whitelist":   {"enabled": True},
        "recent": get_recent(limit=50, event_type="GUARD"),
    })


# ── GET /journal ───────────────────────────────────────────────────────────────

@router.get("/journal")
async def journal(limit: int = 100):
    from execution.trade_journal import get_journal
    return JSONResponse({
        "staging_enabled": JOURNAL_STAGING_ENABLED,
        "auto_approve":    JOURNAL_AUTO_APPROVE,
        "trades":          get_journal(limit),
    })


@router.post("/journal/{trade_hash}/approve", dependencies=_ADMIN)
async def journal_approve(trade_hash: str):
    if not JOURNAL_STAGING_ENABLED:
        raise HTTPException(400, "JOURNAL_STAGING_ENABLED=0 — aucune approbation requise")
    from execution.executor import executor
    if not hasattr(executor, "execute_approved"):
        raise HTTPException(400, "Approbation non disponible pour ce mode d'exécution")
    result = await executor.execute_approved(trade_hash)
    if result is None:
        raise HTTPException(404, f"Trade {trade_hash!r} introuvable ou déjà traité")
    return JSONResponse({"status": "approved", "position": result})


# ── GET /events ────────────────────────────────────────────────────────────────

@router.get("/events")
async def events(limit: int = 100, type: str = ""):
    return JSONResponse({"events": get_recent(limit=limit, event_type=type)})


# ── WS /ws/events ──────────────────────────────────────────────────────────────

@router.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    q = subscribe()
    try:
        for ev in reversed(get_recent(limit=20)):
            await ws.send_json(ev)
        while True:
            ev = await q.get()
            await ws.send_json(ev)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        unsubscribe(q)
