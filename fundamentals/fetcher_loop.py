"""fundamentals/fetcher_loop.py — Boucle asyncio de rafraîchissement des actualités.

Tourne en arrière-plan toutes les FUNDAMENTALS_REFRESH_SEC secondes.
Sauvegarde le score dans data/risk_history.json.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import aiohttp
from utils.config import FUNDAMENTALS_ENABLED, FUNDAMENTALS_REFRESH_SEC, FUNDAMENTALS_HISTORY_FILE
from utils.logger import get_logger
from fundamentals.news_fetcher import fetch_all_news, get_all_text
from fundamentals.risk_scorer import compute_score

logger = get_logger(__name__)

# Cache des derniers articles (partagé avec l'API)
_last_articles: List[Dict[str, Any]] = []
_last_score_result: Dict[str, Any]  = {}
_fetch_lock = asyncio.Lock()


def get_cached_articles() -> List[Dict[str, Any]]:
    return list(_last_articles)


def get_cached_score() -> Dict[str, Any]:
    return dict(_last_score_result)


async def _save_history(score_result: Dict[str, Any]) -> None:
    """Append le score dans risk_history.json."""
    try:
        hist_file = FUNDAMENTALS_HISTORY_FILE
        hist_file.parent.mkdir(parents=True, exist_ok=True)

        history = []
        if hist_file.exists():
            try:
                history = json.loads(hist_file.read_text(encoding="utf-8"))
            except Exception:
                history = []

        history.append({
            "ts":    score_result.get("ts", datetime.now(timezone.utc).isoformat()),
            "score": score_result.get("score", 0),
            "level": score_result.get("level", "UNKNOWN"),
        })
        # Garder 7 jours (672 entrées à 15 min/entrée)
        if len(history) > 672:
            history = history[-672:]

        hist_file.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[FUNDAMENTALS] Sauvegarde historique: %s", e)


async def fundamentals_loop(session: aiohttp.ClientSession) -> None:
    """Boucle principale de rafraîchissement des actualités."""
    global _last_articles, _last_score_result

    if not FUNDAMENTALS_ENABLED:
        logger.info("[FUNDAMENTALS] Module désactivé (FUNDAMENTALS_ENABLED=0)")
        return

    # Premier fetch immédiat
    await asyncio.sleep(10)

    while True:
        async with _fetch_lock:
            try:
                logger.info("[FUNDAMENTALS] Rafraîchissement actualités...")
                articles = await fetch_all_news(session)
                if articles:
                    _last_articles = articles
                    corpus         = get_all_text(articles)
                    score_result   = compute_score(articles, corpus)
                    _last_score_result = score_result
                    await _save_history(score_result)
                    logger.info(
                        "[FUNDAMENTALS] Score=%.1f (%s) | %d articles",
                        score_result["score"], score_result["level"], len(articles),
                    )
                else:
                    logger.warning("[FUNDAMENTALS] Aucun article récupéré")
            except Exception as e:
                logger.error("[FUNDAMENTALS] Erreur fetch: %s", e, exc_info=True)

        await asyncio.sleep(FUNDAMENTALS_REFRESH_SEC)
