"""api/swing_routes.py — Moteur SWING multi-actifs MT5 (paper only).

GET  /swing/status → stats + connexion MT5 + configs du panier
GET  /swing/state  → positions ouvertes, derniers signaux, trades
POST /swing/scan   → force un cycle immédiat
POST /swing/reset  → remet le compte paper swing à zéro
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.auth import require_admin

from core.swing_engine import get_configs, get_stats, scan_once, swing_state, _save
from utils.config import SWING_CAPITAL, SWING_ENABLED
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/swing", tags=["swing"])
_ADMIN = [Depends(require_admin)]


@router.get("/status")
async def swing_status() -> JSONResponse:
    from data.mt5_provider import account_snapshot
    mt5_info = await asyncio.to_thread(account_snapshot)
    return JSONResponse({"enabled": SWING_ENABLED, "mt5": mt5_info,
                         "configs": get_configs(), **get_stats()})


@router.get("/state")
async def swing_full_state() -> JSONResponse:
    return JSONResponse({
        "positions":   swing_state["positions"],
        "last_signal": swing_state["last_signal"],
        "trades":      swing_state["trades"][-30:],
    })


@router.post("/scan", dependencies=_ADMIN)
async def swing_scan() -> JSONResponse:
    if not SWING_ENABLED:
        raise HTTPException(503, "SWING_ENABLED=0 — activer dans .env puis redémarrer")
    report = await scan_once()
    return JSONResponse({"status": "ok", **report, **get_stats()})


@router.get("/risk/exposure")
async def risk_exposure() -> JSONResponse:
    """Expositions gross/net + plafonds R3 (lecture seule, pour l'anneau R3
    de l'orbe du dashboard). `ok=false` = état illisible → garde fail-closed."""
    from core.portfolio_risk import exposure_snapshot
    return JSONResponse(exposure_snapshot())


@router.post("/reset", dependencies=_ADMIN)
async def swing_reset() -> JSONResponse:
    swing_state.update(equity=SWING_CAPITAL, positions={}, trades=[],
                       last_signal={}, errors=[], scan_count=0)
    _save()
    logger.info("[SWING] Compte paper swing remis à zéro (%.0f EUR)", SWING_CAPITAL)
    return JSONResponse({"status": "reset", "equity": SWING_CAPITAL})
