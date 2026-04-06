"""assistant/daily_report.py — Rapport quotidien automatique à 20h.

Génère un rapport complet chaque jour à TITAN_REPORT_HOUR:TITAN_REPORT_MIN.
Le rapport inclut :
  - Performance du jour (PnL, trades, winrate)
  - Positions ouvertes
  - Analyse macro (score risque)
  - Signaux actifs
  - Suggestions d'optimisation de Titan (via LLM)

Titan lit le rapport vocalement avec l'avatar animé.
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp

from assistant.config import (
    TITAN_REPORT_HOUR, TITAN_REPORT_MIN, TITAN_REPORT_ENABLED, TITAN_API_BASE,
)

logger = logging.getLogger(__name__)


async def _fetch(session: aiohttp.ClientSession, path: str) -> Optional[Dict[str, Any]]:
    try:
        async with session.get(
            f"{TITAN_API_BASE}{path}",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as r:
            return await r.json() if r.status == 200 else None
    except Exception:
        return None


async def build_daily_report(session: aiohttp.ClientSession) -> str:
    """Construit le texte du rapport quotidien."""
    now_str = datetime.now().strftime("%A %d %B %Y, %H heures %M")

    # Collecte des données
    state        = await _fetch(session, "/api/state") or {}
    paper_stats  = await _fetch(session, "/paper/stats") or {}
    paper_pos    = await _fetch(session, "/paper/positions") or {}
    fund_state   = await _fetch(session, "/fundamentals/state") or {}

    lines = [f"Rapport Titan du {now_str}."]

    # ── PnL et stats ──────────────────────────────────────────────────────────
    if paper_stats:
        wr    = paper_stats.get("winrate_pct", 0)
        sh    = paper_stats.get("sharpe", 0)
        dd    = paper_stats.get("max_drawdown_pct", 0)
        pnl   = paper_stats.get("total_pnl", 0)
        n     = paper_stats.get("total_trades", 0)
        eq    = paper_stats.get("equity", 0)
        lines.append(
            f"Performance paper trading : {n} trades réalisés, "
            f"P&L total {pnl:+.2f} dollars, "
            f"winrate {wr:.1f} pourcent, "
            f"sharpe {sh:.2f}, "
            f"drawdown maximum {dd:.1f} pourcent, "
            f"équité actuelle {eq:.2f} dollars."
        )
    else:
        lines.append("Aucune statistique paper disponible.")

    # ── Positions ouvertes ────────────────────────────────────────────────────
    positions = paper_pos.get("positions", []) if isinstance(paper_pos, dict) else []
    if positions:
        lines.append(f"{len(positions)} position(s) ouverte(s) :")
        for pos in positions[:3]:  # max 3 pour ne pas être trop long
            sym   = pos.get("symbol", "?")
            side  = pos.get("side", "?")
            pnl_p = pos.get("unrealized_pnl", 0) or 0
            lines.append(
                f"  {sym} {side}, PnL non réalisé {pnl_p:+.2f} dollars."
            )
    else:
        lines.append("Aucune position ouverte.")

    # ── Signaux actifs ────────────────────────────────────────────────────────
    signals = state.get("signals", {})
    active  = [(s, d) for s, d in signals.items() if d.get("active")]
    if active:
        lines.append(f"{len(active)} signal(s) actif(s) : " +
                     ", ".join(f"{s} {d.get('side')} score {d.get('score')}" for s, d in active[:3]))
    else:
        lines.append("Aucun signal actif en ce moment.")

    # ── Risque macro ──────────────────────────────────────────────────────────
    if fund_state:
        risk = fund_state.get("risk_score", 0)
        if risk > 7:
            lines.append(f"Attention : risque macro élevé à {risk:.1f} sur 10. Prudence recommandée.")
        elif risk > 4:
            lines.append(f"Risque macro modéré à {risk:.1f} sur 10.")
        else:
            lines.append(f"Risque macro faible à {risk:.1f} sur 10. Conditions favorables.")

    return " ".join(lines)


async def generate_llm_commentary(
    session: aiohttp.ClientSession,
    report_text: str,
) -> str:
    """Demande à Titan de commenter le rapport et d'ajouter des suggestions."""
    from assistant.titan_agent import ask_titan
    prompt = (
        f"Voici le rapport quotidien de mon bot : {report_text}\n\n"
        "En 2-3 phrases concises, donne-moi ton analyse principale et une suggestion concrète."
    )
    return await ask_titan(prompt, session=session)


async def daily_report_loop(session: Optional[aiohttp.ClientSession] = None) -> None:
    """Boucle infinie — attend l'heure du rapport puis le génère et le lit."""
    if not TITAN_REPORT_ENABLED:
        logger.info("[REPORT] Rapport quotidien désactivé")
        return

    logger.info(
        "[REPORT] Rapport quotidien programmé à %02d:%02d",
        TITAN_REPORT_HOUR, TITAN_REPORT_MIN,
    )

    _own_session = session is None
    if _own_session:
        session = aiohttp.ClientSession()

    try:
        while True:
            # Calculer le délai jusqu'à la prochaine occurrence
            now    = datetime.now()
            target = now.replace(
                hour=TITAN_REPORT_HOUR,
                minute=TITAN_REPORT_MIN,
                second=0,
                microsecond=0,
            )
            if target <= now:
                # Déjà passé aujourd'hui → demain
                from datetime import timedelta
                target += timedelta(days=1)

            delay = (target - now).total_seconds()
            logger.info("[REPORT] Prochain rapport dans %.0f secondes (%s)", delay,
                        target.strftime("%H:%M"))
            await asyncio.sleep(delay)

            # Heure du rapport
            logger.info("[REPORT] Génération du rapport quotidien…")
            try:
                report_text  = await build_daily_report(session)
                commentary   = await generate_llm_commentary(session, report_text)
                full_text    = report_text + " " + commentary

                from assistant.popup_manager import titan_speak
                await titan_speak(full_text, expression="neutral")
                logger.info("[REPORT] Rapport lu avec succès")

            except Exception as e:
                logger.error("[REPORT] Erreur génération rapport: %s", e)

    finally:
        if _own_session:
            await session.close()
