"""api/emotion_routes.py — Segment ÉMOTION en LECTURE SEULE (v12, 15/07/2026).

GET /emotion                  → émotion de marché des actifs crypto suivis
GET /emotion/{symbole}        → émotion d'un actif : crypto ('BTC/USDT') OU MT5 ('US50', 'XAUUSD')
    ?context=true             → joint le contexte brut réellement lu (transparence/debug)

Lit les VRAIES données via emotion/market_context.py : côté crypto le delta-volume
Binance, le funding/long-short futures, le score macro et les bougies ; côté MT5/Axi
les bougies M15 + le dernier tick (là où passent les vrais trades). Fail-safe : une
source absente est omise et la confiance baisse d'elle-même.

⚠️ READ-ONLY. Le segment ne pilote AUCUNE décision de trading. Tout branchement
décisionnel exige le protocole M2 (verdict Codex : REQUEST_CHANGES_BEFORE_M2 sur
les risques de modèle : corrélation des signaux, seuils non normalisés par actif,
absence d'hystérésis, fraîcheur globale plutôt que par signal).
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from emotion.market_context import _is_crypto, build_context, emotion_for
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/emotion", tags=["emotion"])

_NOTE = "READ-ONLY — aucun usage décisionnel sans protocole M2"


async def _state(symbol: str):
    """MT5 est bloquant (verrou mt5_lock) → thread. Le crypto lit des stores en mémoire."""
    if _is_crypto(symbol):
        return emotion_for(symbol)
    return await asyncio.to_thread(emotion_for, symbol)


@router.get("")
async def emotion_all() -> JSONResponse:
    """Émotion des actifs crypto suivis (lecture mémoire, non bloquante)."""
    from utils.config import SYMBOLS
    out: dict = {}
    for sym in SYMBOLS:
        try:
            out[sym] = asdict(await _state(sym))
        except Exception as exc:                      # une source cassée n'écroule pas la vue
            logger.warning("[EMOTION] %s : %s", sym, exc)
            out[sym] = {"available": False, "error": type(exc).__name__}
    return JSONResponse({"read_only": _NOTE, "symbols": out})


@router.get("/{symbol:path}")
async def emotion_one(symbol: str, context: bool = False) -> JSONResponse:
    """Émotion d'un actif. Le symbole peut contenir un '/' (crypto Binance)."""
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbole requis")
    try:
        state = await _state(symbol)
    except Exception as exc:
        logger.warning("[EMOTION] %s : %s", symbol, exc)
        raise HTTPException(status_code=502,
                            detail=f"lecture émotion impossible ({type(exc).__name__})")
    body = {"symbol": symbol, "source": "binance" if _is_crypto(symbol) else "mt5",
            "read_only": _NOTE, "emotion": asdict(state)}
    if context:
        try:
            body["context"] = (build_context(symbol) if _is_crypto(symbol)
                               else await asyncio.to_thread(build_context, symbol))
        except Exception as exc:
            body["context"] = {"error": type(exc).__name__}
    return JSONResponse(body)
