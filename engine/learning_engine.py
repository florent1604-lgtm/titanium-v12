"""engine/learning_engine.py — Adaptation des poids de scoring + circuit breaker.

Fixes appliqués :
  - Trigger d'adaptation tous les LEARNING_TRIGGER_SIGNALS (50) nouveaux signaux
    en plus du trigger temporel (2h) — le plus rapide gagne
  - Circuit breaker : winrate rolling < 30% sur 20 derniers trades résolus
    → réinitialise les poids au neutre et bloque les signaux temporairement
  - Suivi du compteur de signaux par symbole pour le trigger count-based
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from utils.config import (
    SYMBOLS, SCORE_CRITERIA, SIGNAL_HISTORY_FILE, SCORING_WEIGHTS_FILE,
    LEARNING_REPORT_EVERY, LEARNING_MIN_SIGNALS, LEARNING_ADAPT_RATE,
    LEARNING_TRIGGER_SIGNALS, CIRCUIT_BREAKER_WINRATE_MIN,
    CIRCUIT_BREAKER_ROLLING_N,
)
from utils.logger import get_logger

logger = get_logger(__name__)

signal_history:  Dict[str, List[dict]]    = {s: [] for s in SYMBOLS}
scoring_weights: Dict[str, Dict[str, float]] = {
    s: {c: 1.0 for c in SCORE_CRITERIA} for s in SYMBOLS
}
_learning_lock = asyncio.Lock()

# Compteur de nouveaux signaux depuis le dernier adapt (trigger count-based)
_signals_since_adapt: Dict[str, int] = {s: 0 for s in SYMBOLS}


def load_state() -> None:
    """Charge signal_history et scoring_weights depuis les fichiers JSON."""
    global signal_history, scoring_weights
    try:
        if SIGNAL_HISTORY_FILE.exists():
            raw = json.loads(SIGNAL_HISTORY_FILE.read_text(encoding="utf-8"))
            for sym in SYMBOLS:
                if sym in raw:
                    signal_history[sym] = list(raw[sym])[-500:]
    except Exception as e:
        logger.warning("[LEARNING] Chargement signal_history: %s", e)
    try:
        if SCORING_WEIGHTS_FILE.exists():
            raw = json.loads(SCORING_WEIGHTS_FILE.read_text(encoding="utf-8"))
            for sym in SYMBOLS:
                if sym in raw:
                    for c in SCORE_CRITERIA:
                        if c in raw[sym]:
                            scoring_weights[sym][c] = float(raw[sym][c])
    except Exception as e:
        logger.warning("[LEARNING] Chargement scoring_weights: %s", e)


def save_state() -> None:
    """Sauvegarde signal_history et scoring_weights."""
    try:
        SIGNAL_HISTORY_FILE.write_text(
            json.dumps({s: signal_history[s] for s in SYMBOLS}, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("[LEARNING] save signal_history: %s", e)
    try:
        SCORING_WEIGHTS_FILE.write_text(
            json.dumps(scoring_weights), encoding="utf-8",
        )
    except Exception as e:
        logger.error("[LEARNING] save scoring_weights: %s", e)


def record_signal(sym: str, signal: dict) -> None:
    """Enregistre un signal émis et incrémente le compteur pour le trigger count-based."""
    signal_history[sym].append({
        **signal,
        "ts":      datetime.now(timezone.utc).isoformat(),
        "outcome": "pending",
    })
    if len(signal_history[sym]) > 500:
        signal_history[sym] = signal_history[sym][-500:]

    _signals_since_adapt[sym] += 1

    # Trigger count-based — adapter si on atteint le seuil
    if _signals_since_adapt[sym] >= LEARNING_TRIGGER_SIGNALS:
        logger.info("[LEARNING] %s seuil %d signaux atteint → adaptation anticipée",
                    sym, LEARNING_TRIGGER_SIGNALS)
        _adapt_weights(sym)
        _check_circuit_breaker(sym)
        _signals_since_adapt[sym] = 0
        save_state()


def _reset_weights(sym: str, reason: str) -> None:
    """Réinitialise les poids à 1.0 (neutre)."""
    for c in SCORE_CRITERIA:
        scoring_weights[sym][c] = 1.0
    logger.warning("[LEARNING] %s poids réinitialisés — %s", sym, reason)


def _adapt_weights(sym: str) -> None:
    """Adapte les poids selon les outcomes des signaux (tp = bon, sl = mauvais)."""
    history = [s for s in signal_history[sym] if s.get("outcome") not in ("pending", "expired")]
    if len(history) < LEARNING_MIN_SIGNALS:
        return

    for c in SCORE_CRITERIA:
        with_criterion = [s for s in history if c in s.get("confs", [])]
        if not with_criterion:
            continue
        wins    = sum(1 for s in with_criterion if "tp" in s.get("outcome", ""))
        total   = len(with_criterion)
        win_rate = wins / total

        current = scoring_weights[sym].get(c, 1.0)
        delta   = LEARNING_ADAPT_RATE * (win_rate - 0.6)
        new_w   = max(0.5, min(2.0, current + delta))
        scoring_weights[sym][c] = round(new_w, 4)

    logger.info("[LEARNING] %s poids adaptés (%d signaux résolus)", sym, len(history))


def _check_circuit_breaker(sym: str) -> None:
    """Vérifie le winrate rolling et active/désactive le circuit breaker.

    Condition : winrate sur les N derniers trades résolus < CIRCUIT_BREAKER_WINRATE_MIN
    Action : réinitialise les poids + bloque les signaux via signal_manager
    """
    # Import ici pour éviter la dépendance circulaire
    from execution.signal_manager import set_circuit_breaker, is_circuit_breaker_active

    resolved = [s for s in signal_history[sym] if s.get("outcome") not in ("pending", "expired")]
    if len(resolved) < CIRCUIT_BREAKER_ROLLING_N:
        # Pas assez de données — désactiver si actif
        if is_circuit_breaker_active(sym):
            set_circuit_breaker(sym, False)
        return

    last_n   = resolved[-CIRCUIT_BREAKER_ROLLING_N:]
    wins     = sum(1 for s in last_n if "tp" in s.get("outcome", ""))
    winrate  = wins / len(last_n)

    if winrate < CIRCUIT_BREAKER_WINRATE_MIN:
        if not is_circuit_breaker_active(sym):
            _reset_weights(sym, f"winrate={winrate:.0%} < {CIRCUIT_BREAKER_WINRATE_MIN:.0%}")
            set_circuit_breaker(sym, True,
                f"winrate {winrate:.0%} < seuil {CIRCUIT_BREAKER_WINRATE_MIN:.0%}")
    else:
        if is_circuit_breaker_active(sym):
            set_circuit_breaker(sym, False)
            logger.info("[LEARNING] %s winrate rétabli (%.0%%) — reprise des signaux", sym, winrate)


async def learning_report_loop() -> None:
    """Boucle d'adaptation des poids (trigger temporel toutes les 2h)."""
    await asyncio.sleep(120)
    while True:
        async with _learning_lock:
            for sym in SYMBOLS:
                try:
                    _adapt_weights(sym)
                    _check_circuit_breaker(sym)
                    _signals_since_adapt[sym] = 0   # reset compteur après run temporel
                except Exception as e:
                    logger.error("[LEARNING] %s: %s", sym, e)
            save_state()
        await asyncio.sleep(LEARNING_REPORT_EVERY)


def get_weights(sym: str) -> Dict[str, float]:
    return dict(scoring_weights.get(sym, {c: 1.0 for c in SCORE_CRITERIA}))
