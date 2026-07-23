"""api/fundamentals_routes.py — Routes FastAPI pour le module Fundamentals.

Endpoints :
  GET  /fundamentals/score    → score de risque courant + niveau
  GET  /fundamentals/news     → derniers articles agrégés
  GET  /fundamentals/history  → historique du score (7 jours)
  POST /fundamentals/reload   → force un refresh immédiat
  POST /fundamentals/enable   → active le module (runtime)
  POST /fundamentals/disable  → désactive le module (runtime)
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request as FARequest, HTTPException
from fastapi.responses import JSONResponse
from api.auth import require_admin
from utils.config import FUNDAMENTALS_HISTORY_FILE
from utils.logger import get_logger
from fundamentals.risk_scorer import get_current_score, get_score_history
from fundamentals.signal_modulator import (
    is_active, force_enable, force_disable, get_modulation_stats,
)
from fundamentals.fetcher_loop import get_cached_articles, get_cached_score

logger = get_logger(__name__)
router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])
_ADMIN = [Depends(require_admin)]


@router.get("/score")
async def api_fundamentals_score():
    """Score de risque macroéconomique courant."""
    cached = get_cached_score()
    return JSONResponse({
        **cached,
        "module_active": is_active(),
        "modulation":    get_modulation_stats(),
    })


@router.get("/news")
async def api_fundamentals_news(limit: int = 30):
    """Derniers articles agrégés (titre, source, url)."""
    articles = get_cached_articles()
    # Ne pas exposer les descriptions complètes (confidentialité)
    safe = [
        {
            "title":   a.get("title", "")[:200],
            "source":  a.get("source", ""),
            "url":     a.get("url", ""),
            "published": a.get("published", ""),
        }
        for a in articles[:limit]
    ]
    return JSONResponse({"articles": safe, "total": len(articles)})


@router.get("/history")
async def api_fundamentals_history():
    """Historique du score de risque (max 7 jours)."""
    try:
        hist_file = FUNDAMENTALS_HISTORY_FILE
        if hist_file.exists():
            history = json.loads(hist_file.read_text(encoding="utf-8"))
        else:
            history = []
    except Exception:
        history = []

    return JSONResponse({"history": history[-200:], "total": len(history)})


@router.post("/reload", dependencies=_ADMIN)
async def api_fundamentals_reload(request: FARequest):
    """Force un refresh immédiat des actualités."""
    session = request.app.state.http
    try:
        from fundamentals.news_fetcher import fetch_all_news, get_all_text
        from fundamentals.risk_scorer import compute_score
        from fundamentals.fetcher_loop import _last_articles, _last_score_result

        articles = await fetch_all_news(session)
        if articles:
            corpus = get_all_text(articles)
            result = compute_score(articles, corpus)
            return JSONResponse({"status": "refreshed", **result})
        return JSONResponse({"status": "no_articles", "score": get_current_score()})
    except Exception as e:
        logger.error("[FUNDAMENTALS API] reload error: %s", e)
        raise HTTPException(500, str(e))


@router.post("/enable", dependencies=_ADMIN)
async def api_fundamentals_enable():
    """Active le module Fundamentals (sans redémarrage)."""
    force_enable()
    return JSONResponse({"status": "enabled", "active": True})


@router.post("/disable", dependencies=_ADMIN)
async def api_fundamentals_disable():
    """Désactive le module Fundamentals (sans redémarrage)."""
    force_disable("désactivé via API")
    return JSONResponse({"status": "disabled", "active": False})
