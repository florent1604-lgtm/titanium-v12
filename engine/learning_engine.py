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
    CIRCUIT_BREAKER_ROLLING_N, PAPER_JOURNAL_FILE,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Mapping SCORE_CRITERIA → préfixes de labels humains ──────────────────────
# Les confs dans le journal paper utilisent des labels lisibles ("EMA200-H4 haussier")
# tandis que SCORE_CRITERIA utilise des clés normalisées ("EMA200_H4").
# Ce mapping permet le matching entre les deux.
_CRITERIA_LABEL_PREFIXES: Dict[str, list] = {
    "EMA200_H4":          ["EMA200-H4", "EMA200_H4"],
    "STRUCT_H2H1":        ["BOS H2", "BOS H1", "CHoCH"],
    "OB_FVG_30M":         ["OB/FVG 30m"],
    "OB_FVG_15M_CONFIRM": ["OB/FVG double conf", "OB/FVG 15m"],
    "REJET_15M":          ["Rejet 5m", "Rejet 15m"],
    "TRIX_5M":            ["TRIX 5m", "TRIX"],
    "ALIGN_H2H1":         ["H2+H1 align"],
    "EMA200_1D":          ["EMA200-1D", "Biais D1"],
    "DELTA_VOL":          ["Delta volume"],
    "LIQ_SWEEP":          ["Liquidity sweep"],
    "ADX_REGIME":         ["ADX r\u00e9gime", "ADX regime"],
    "RSI_DIVERGENCE":     ["RSI divergence"],
    "VOL_SPIKE":          ["Vol spike", "Volume spike"],
    "DISPLACEMENT":       ["Displacement"],
    "ORDERBOOK_IMBALANCE":["OB L2 imbalance"],
    "ORDERBOOK_WALL":     ["OB wall"],
}


def _criterion_in_confs(criterion: str, confs: list) -> bool:
    """Vérifie si un critère SCORE_CRITERIA est présent dans les confs humaines."""
    prefixes = _CRITERIA_LABEL_PREFIXES.get(criterion, [criterion])
    return any(
        any(conf.startswith(prefix) or prefix.lower() in conf.lower()
            for prefix in prefixes)
        for conf in confs
    )


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
    """Adapte les poids selon signal_history + journal paper trading.

    Deux sources de données (la plus fiable prime) :
      1. signal_history.json — signaux avec outcomes résolus (tp/sl)
      2. paper_journal.json  — trades fermés avec PnL réel (source de vérité)
    """
    # ── Source 1 : signal_history ──────────────────────────────────────────────
    history = [s for s in signal_history[sym] if s.get("outcome") not in ("pending", "expired")]
    if len(history) >= LEARNING_MIN_SIGNALS:
        adapted_count = 0
        for c in SCORE_CRITERIA:
            with_criterion = [s for s in history if _criterion_in_confs(c, s.get("confs", []))]
            if not with_criterion:
                continue
            wins     = sum(1 for s in with_criterion if "tp" in s.get("outcome", ""))
            win_rate = wins / len(with_criterion)
            current  = scoring_weights[sym].get(c, 1.0)
            delta    = LEARNING_ADAPT_RATE * (win_rate - 0.6)
            scoring_weights[sym][c] = round(max(0.5, min(2.0, current + delta)), 4)
            adapted_count += 1
        logger.info("[LEARNING] %s poids adaptés signal_history (%d résolus, %d critères)",
                    sym, len(history), adapted_count)

    # ── Source 2 : paper journal (source de vérité — PnL réel) ────────────────
    _adapt_from_paper_journal(sym)


def _adapt_from_paper_journal(sym: str) -> None:
    """Adapte les poids depuis le journal paper trading (outcomes certains).

    Pour chaque critère SMC, calcule le winrate sur les trades où il était actif.
    Applique la même formule que _adapt_weights (delta = rate × (wr - 0.6)).
    Idempotent : peut être appelé plusieurs fois sur les mêmes données.
    """
    try:
        if not PAPER_JOURNAL_FILE.exists():
            return
        all_trades = json.loads(PAPER_JOURNAL_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("[LEARNING] Lecture journal paper: %s", e)
        return

    sym_trades = [t for t in all_trades if t.get("symbol") == sym]
    if len(sym_trades) < LEARNING_MIN_SIGNALS:
        return

    adapted_count = 0
    for c in SCORE_CRITERIA:
        crit_trades = [t for t in sym_trades if _criterion_in_confs(c, t.get("confs", []))]
        if len(crit_trades) < 3:  # pas assez de données pour ce critère
            continue
        wins     = sum(1 for t in crit_trades if float(t.get("pnl_usdt", 0)) > 0)
        win_rate = wins / len(crit_trades)
        current  = scoring_weights[sym].get(c, 1.0)
        # Poids moindre sur le journal paper (factor 0.5) pour ne pas trop surpondérer
        delta    = LEARNING_ADAPT_RATE * 0.5 * (win_rate - 0.6)
        scoring_weights[sym][c] = round(max(0.5, min(2.0, current + delta)), 4)
        adapted_count += 1

    logger.info(
        "[LEARNING] %s poids adaptés journal paper (%d trades, critères: %d actifs)",
        sym, len(sym_trades), adapted_count,
    )


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
            logger.info("[LEARNING] %s winrate rétabli (%.0f%%) — reprise des signaux", sym, winrate * 100)


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
