"""api/paper_routes.py — Routes REST pour le Paper Trading Engine.

Endpoints :
  GET  /paper/state         Equity, positions ouvertes, stats résumées
  GET  /paper/positions     Positions ouvertes (avec PnL non réalisé)
  GET  /paper/trades        Historique des trades fermés
  GET  /paper/stats         Statistiques complètes (winrate, sharpe, etc.)
  GET  /paper/equity-curve  Points de l'equity curve
  POST /paper/reset         Remet le compte à zéro
  POST /paper/close/{sym}   Fermeture manuelle d'une position
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FARequest
from fastapi.responses import JSONResponse

from api.auth import require_admin
from utils.config import TRADING_MODE, SYMBOLS
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/paper", tags=["paper"])
_ADMIN = [Depends(require_admin)]


def _exec():
    from execution.executor import executor
    return executor


# ── GET /paper/state ──────────────────────────────────────────────────────────

@router.get("/state")
async def paper_state():
    """État complet du compte paper (equity + positions + stats)."""
    exc = _exec()
    return JSONResponse(exc.get_state())


# ── GET /paper/positions ──────────────────────────────────────────────────────

@router.get("/positions")
async def paper_positions():
    """Positions actuellement ouvertes avec PnL non réalisé."""
    exc = _exec()
    state = exc.get_state()
    return JSONResponse({
        "mode":      state.get("mode", TRADING_MODE),
        "positions": state.get("positions", {}),
        "count":     len(state.get("positions", {})),
    })


# ── GET /paper/trades ─────────────────────────────────────────────────────────

@router.get("/trades")
async def paper_trades(limit: int = 50):
    """Historique des trades fermés (les plus récents en premier)."""
    exc = _exec()
    state = exc.get_state()
    trades = list(reversed(state.get("recent_trades", [])))
    total  = len(trades)
    return JSONResponse({
        "mode":   state.get("mode", TRADING_MODE),
        "total":  total,
        "trades": trades[:limit],
    })


# ── GET /paper/stats ──────────────────────────────────────────────────────────

@router.get("/stats")
async def paper_stats():
    """Statistiques de performance complètes."""
    exc = _exec()
    state = exc.get_state()
    return JSONResponse(state.get("stats", {"mode": TRADING_MODE}))


# ── GET /paper/equity-curve ───────────────────────────────────────────────────

@router.get("/equity-curve")
async def paper_equity_curve(last_n: int = 200):
    """Points de l'equity curve [{ts, equity, dd_pct}]."""
    exc = _exec()
    if not hasattr(exc, "get_equity_curve"):
        return JSONResponse({"equity_curve": [], "mode": TRADING_MODE})
    return JSONResponse({
        "equity_curve": exc.get_equity_curve(last_n),
        "mode":         TRADING_MODE,
    })


# ── POST /paper/reset ─────────────────────────────────────────────────────────

@router.post("/reset", dependencies=_ADMIN)
async def paper_reset(request: FARequest):
    """Remet le compte paper à zéro — IRRÉVERSIBLE.

    Requiert le header X-Reset-Confirm: yes pour éviter les resets accidentels.
    """
    confirm = request.headers.get("X-Reset-Confirm", "").strip().lower()
    if confirm != "yes":
        raise HTTPException(
            400,
            "Requiert le header X-Reset-Confirm: yes — opération irréversible"
        )
    exc = _exec()
    if TRADING_MODE == "disabled":
        raise HTTPException(400, "Mode paper inactif (TRADING_MODE=disabled)")
    if not hasattr(exc, "reset"):
        raise HTTPException(400, "Reset non disponible pour ce mode")
    await exc.reset()
    return {"status": "ok", "message": "Compte paper réinitialisé avec succès"}


# ── POST /paper/reset-circuit-breaker ────────────────────────────────────────

@router.post("/reset-circuit-breaker", dependencies=_ADMIN)
async def reset_circuit_breaker():
    """Désactive le circuit breaker sur tous les symboles et remet signal_history à zéro.

    Utile quand le CB s'est déclenché sur des données historiques obsolètes.
    """
    from execution.signal_manager import set_circuit_breaker, is_circuit_breaker_active
    from engine.learning_engine import signal_history, save_state
    from utils.config import SYMBOLS

    reset_syms = []
    for sym in SYMBOLS:
        if is_circuit_breaker_active(sym):
            set_circuit_breaker(sym, False)
            reset_syms.append(sym)
        signal_history[sym].clear()

    save_state()
    return JSONResponse({
        "status":       "ok",
        "reset_symbols": reset_syms,
        "message":      f"Circuit breaker désactivé + signal_history vidé pour {len(SYMBOLS)} symboles",
    })


# ── POST /paper/close/{symbol} ────────────────────────────────────────────────

@router.post("/close/{symbol}", dependencies=_ADMIN)
async def paper_close(symbol: str, request: FARequest):
    """Ferme manuellement une position au prix indiqué.

    Body JSON : {"price": 12345.67}
    """
    exc = _exec()
    if TRADING_MODE == "disabled":
        raise HTTPException(400, "Mode paper inactif")
    if not hasattr(exc, "close_position_manual"):
        raise HTTPException(400, "Fermeture manuelle non disponible")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    price = float(body.get("price", 0))
    if price <= 0:
        raise HTTPException(422, "Prix requis (body JSON: {\"price\": 12345.67})")

    # Normaliser le symbole
    sym = symbol.upper()
    if "/" not in sym:
        sym = sym.replace("USDT", "/USDT")
    if sym not in SYMBOLS:
        raise HTTPException(404, f"Symbole {sym!r} non suivi")

    trade = await exc.close_position_manual(sym, price)
    if trade is None:
        raise HTTPException(404, f"Aucune position ouverte sur {sym}")

    return JSONResponse({
        "status": "closed",
        "trade":  trade.to_dict() if hasattr(trade, "to_dict") else trade,
    })
