"""execution/demo_bridge.py — Pont moteurs paper → exécution DÉMO réelle.

Quand un moteur (swing/forex) ouvre une position PAPER sur un signal validé, ce
pont place EN PARALLÈLE un ordre réel sur le compte DÉMO — sous tous les
garde-fous de `demo_mt5_executor` (fail-closed démo, plafonds, spread).

Sûr par construction :
  - désarmé si `DEMO_EXEC_ENABLED != 1` ;
  - passe par `mt5_lock` (MT5 non thread-safe) ;
  - dédup : n'ouvre pas si une position démo existe déjà sur ce symbole ;
  - respecte `DEMO_MAX_POSITIONS` ;
  - non fatal : toute erreur est journalisée, le paper continue normalement.

Le broker démo gère lui-même SL/TP (posés à l'ouverture) — pas de gestion de
sortie ici pour cette première version.
"""
from __future__ import annotations

import asyncio
import os

from utils.logger import get_logger
from execution import demo_mt5_executor as dx

logger = get_logger(__name__)


def _pos_side(pos) -> str:
    """Sens d'une position MT5 (type 0=buy→long, 1=sell→short)."""
    return "long" if int(getattr(pos, "type", 0)) == 0 else "short"


def _pos_quality(pos) -> int:
    """Qualité de structure encodée à l'ouverture dans le commentaire (« …|p4 »).
    Positions antérieures à cette convention → qualité 0."""
    c = str(getattr(pos, "comment", "") or "")
    if "|p" in c:
        try:
            return int(c.rsplit("|p", 1)[1])
        except (ValueError, IndexError):
            return 0
    return 0


def _place_sync(symbol: str, side: str, atr: float,
                sl_atr_mult: float, tp_atr_mult: float,
                comment: str = "titanium-demo", size_factor: float = 1.0,
                quality: int = 0) -> dict | None:
    """Travail bloquant exécuté dans un thread, sous mt5_lock.
    `quality` = nombre de piliers de confluence du setup (proxy de qualité), encodé
    dans le commentaire de l'ordre pour arbitrer les multi-positions par actif."""
    import MetaTrader5 as mt5
    from data.mt5_provider import mt5_lock

    guards = dx.DemoGuards.from_env()
    if not guards.enabled:
        return None
    with mt5_lock:
        # DÉDUP / MULTI-POSITION PAR ACTIF (Florent 25/07). FAIL-CLOSED (P0-2 Codex) :
        # toute indisponibilité de positions_get REFUSE au lieu d'ouvrir un doublon.
        try:
            existing = mt5.positions_get(symbol=symbol)
        except Exception:
            return {"sent": False, "reason": "POSITIONS_UNAVAILABLE"}
        if existing is None:
            return {"sent": False, "reason": "POSITIONS_UNAVAILABLE"}
        n_exist = len(existing)
        max_per = max(1, int(getattr(guards, "max_pos_per_symbol", 1)))
        if n_exist >= max_per:
            return {"sent": False, "reason": f"MAX_POS_PER_SYMBOL: {n_exist}/{max_per} déjà ouvertes"}
        if n_exist > 0:
            # Empilement autorisé UNIQUEMENT si le nouveau setup est meilleur et de même sens.
            # 1) même sens (on empile dans la tendance, pas de hedge long+short stérile) :
            if any(_pos_side(p) != side for p in existing):
                return {"sent": False, "reason": "OPPOSITE_SIDE_OPEN: sens opposé déjà ouvert"}
            # 2) STRICTEMENT meilleur : plus de piliers que la meilleure position en cours :
            best_prev = max((_pos_quality(p) for p in existing), default=0)
            if int(quality) <= best_prev:
                return {"sent": False,
                        "reason": f"NOT_BETTER_SETUP: p{int(quality)} <= p{best_prev} en cours"}
        # Trace la qualité dans le commentaire (tronqué à 27 char, limite broker MT5).
        comment = f"{comment}|p{int(quality)}"[:27]
        # plafond global — fail-closed aussi
        try:
            allpos = mt5.positions_get()
        except Exception:
            return {"sent": False, "reason": "POSITIONS_UNAVAILABLE"}
        if allpos is None:
            return {"sent": False, "reason": "POSITIONS_UNAVAILABLE"}
        if len(allpos) >= guards.max_positions:
            return {"sent": False, "reason": "MAX_POSITIONS"}
        # référence journalière (kill-switch actif) établie AVANT l'ordre
        try:
            acc = dx.assert_demo_or_raise(mt5)
            dse = dx.establish_day_ref(acc["equity"])
        except dx.DemoExecutionRefused as exc:
            return {"sent": False, "reason": str(exc)}
        return dx.place_market_order(mt5, symbol, side, atr,
                                     sl_atr_mult=sl_atr_mult, tp_atr_mult=tp_atr_mult,
                                     guards=guards, day_start_equity=dse, comment=comment,
                                     size_factor=size_factor)


async def place_demo_async(symbol: str, side: str, atr: float,
                           sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0,
                           engine: str = "?", size_factor: float = 1.0,
                           quality: int = 0) -> dict | None:
    """À appeler après une ouverture paper. Non bloquant pour la boucle, non fatal.
    `size_factor` = conviction (émotion) → taille, transmis à l'exécuteur démo.
    `quality` = nb de piliers de confluence → arbitre les multi-positions par actif."""
    if os.getenv("DEMO_EXEC_ENABLED", "0") != "1":
        return None
    comment = "titanium-aggr" if "aggr" in str(engine).lower() else "titanium-conf"
    try:
        res = await asyncio.to_thread(_place_sync, symbol, side, atr,
                                      sl_atr_mult, tp_atr_mult, comment, size_factor,
                                      quality)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DEMO] pont erreur %s: %r", symbol, exc)
        return None
    if res and res.get("sent"):
        logger.info("[DEMO] ordre DÉMO placé %s %s lot %s @ %s (risque %s)",
                    symbol, side, res.get("lot"), res.get("price"), res.get("risk_money"))
        # Alerte SONORE à l'ouverture (Florent). Non bloquant, fail-safe.
        try:
            from execution.trade_alert import demo_trade_opened
            demo_trade_opened(symbol, side)
        except Exception:
            pass
    elif res and res.get("reason"):
        logger.info("[DEMO] %s non placé — %s", symbol, res["reason"])

    # Traçabilité : chaque tentative est ÉCRITE (envoyée ou refusée, avec sa
    # raison) + l'émotion OBSERVÉE à l'instant de la décision. Jamais bloquant :
    # journaliser ne doit pas pouvoir casser un ordre (to_thread → l'émotion MT5
    # prend le verrou mt5_lock, on ne le tient pas ici).
    if res is not None:
        try:
            from execution import demo_journal
            await asyncio.to_thread(demo_journal.record, symbol, side, res,
                                    atr=atr, engine=engine)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DEMO] journal non écrit %s: %r", symbol, exc)
    return res
