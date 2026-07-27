"""fundamentals/signal_modulator.py — Modulation des signaux SMC par le risque macro.

Logique de modulation :
  - risk_score > FUNDAMENTALS_RISK_BLOCK (70)  → signal annulé (None)
  - risk_score > FUNDAMENTALS_RISK_REDUCE (30) → score réduit proportionnellement
  - risk_score <= FUNDAMENTALS_RISK_REDUCE      → signal inchangé

Formule de réduction :
  factor = 1 - ((risk_score - REDUCE_THRESHOLD) / (BLOCK_THRESHOLD - REDUCE_THRESHOLD)) × 0.5
  score_final = int(score_smc × factor)

Auto-rollback :
  Si le Sharpe glissant (20 derniers signaux modulés résolus) baisse > 0.3
  vs les signaux non-modulés → feature flag basculé à False + alerte écrite.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from utils.config import (
    FUNDAMENTALS_ENABLED,
    FUNDAMENTALS_RISK_BLOCK, FUNDAMENTALS_RISK_REDUCE,
    FUNDAMENTALS_ROLLBACK_DELTA,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Réorg Phase 1.5 : ce module a été déplacé de fundamentals/ vers poles/fundamentals/ (un
# niveau plus profond). ALERT_FUNDAMENTALS.md reste à la RACINE du dépôt → parents[2] (et non
# plus parent.parent) pour cibler le même fichier qu'avant. tuning_log.md suit le module.
_ALERT_FILE = Path(__file__).resolve().parents[2] / "ALERT_FUNDAMENTALS.md"
_TUNING_LOG = Path(__file__).parent / "tuning_log.md"

# Feature flag runtime (peut être désactivé sans redémarrage)
_fundamentals_active: bool = FUNDAMENTALS_ENABLED

# Historique des modulations pour le rollback automatique
_modulation_history: List[Dict[str, Any]] = []


def is_active() -> bool:
    return _fundamentals_active


def force_disable(reason: str) -> None:
    """Désactive le module et écrit une alerte."""
    global _fundamentals_active
    _fundamentals_active = False

    msg = (
        f"# ALERT — Module Fundamentals désactivé\n\n"
        f"**Date** : {datetime.now(timezone.utc).isoformat()}\n"
        f"**Raison** : {reason}\n\n"
        f"Pour réactiver : `FUNDAMENTALS_ENABLED=1` dans `.env` et redémarrer.\n"
    )
    try:
        _ALERT_FILE.write_text(msg, encoding="utf-8")
    except Exception:
        pass

    _log_tuning(f"AUTO-DISABLE: {reason}")
    logger.warning("[MODULATOR] Module désactivé — %s", reason)


def force_enable() -> None:
    global _fundamentals_active
    _fundamentals_active = True
    _log_tuning("RE-ENABLE: module réactivé manuellement")
    logger.info("[MODULATOR] Module réactivé")


def _log_tuning(event: str) -> None:
    """Append une ligne dans tuning_log.md."""
    line = f"- `{datetime.now(timezone.utc).isoformat()}` — {event}\n"
    try:
        with open(_TUNING_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def modulate(
    signal: Dict[str, Any],
    risk_score: float,
) -> Optional[Dict[str, Any]]:
    """Applique le filtre macro sur un signal SMC.

    Args:
        signal     : signal SMC tel que produit par emit_signal (doit avoir "score", "side")
        risk_score : score de risque courant (0–100)

    Returns:
        Signal modifié, ou None si annulé.
    """
    if not _fundamentals_active:
        return signal   # module désactivé → passe-through

    original_score = signal.get("score", 0)
    sym            = signal.get("symbol", "?")

    # ── Blocage total ─────────────────────────────────────────────────────────
    if risk_score >= FUNDAMENTALS_RISK_BLOCK:
        logger.info(
            "[MODULATOR] %s — signal ANNULÉ risk_score=%.1f >= %.1f",
            sym, risk_score, FUNDAMENTALS_RISK_BLOCK,
        )
        _record_modulation(sym, original_score, 0, risk_score, "blocked")
        return None

    # ── Réduction proportionnelle ─────────────────────────────────────────────
    if risk_score > FUNDAMENTALS_RISK_REDUCE:
        spread = FUNDAMENTALS_RISK_BLOCK - FUNDAMENTALS_RISK_REDUCE
        factor = 1.0 - ((risk_score - FUNDAMENTALS_RISK_REDUCE) / spread) * 0.5
        factor = round(max(0.5, min(1.0, factor)), 4)
        new_score = max(0, int(original_score * factor))

        modulated = {
            **signal,
            "score":        new_score,
            "risk_score":   round(risk_score, 1),
            "risk_factor":  factor,
            "risk_level":   _level(risk_score),
            "score_original": original_score,
        }
        logger.info(
            "[MODULATOR] %s — score %d→%d factor=%.2f risk=%.1f",
            sym, original_score, new_score, factor, risk_score,
        )
        _record_modulation(sym, original_score, new_score, risk_score, "reduced")
        return modulated

    # ── Passe-through ─────────────────────────────────────────────────────────
    signal_out = {
        **signal,
        "risk_score":  round(risk_score, 1),
        "risk_factor": 1.0,
        "risk_level":  _level(risk_score),
    }
    _record_modulation(sym, original_score, original_score, risk_score, "pass")
    return signal_out


def _level(score: float) -> str:
    if score >= 75: return "EXTREME"
    if score >= 55: return "HIGH"
    if score >= 35: return "MEDIUM"
    if score >= 15: return "LOW"
    return "CALM"


def _record_modulation(
    sym: str,
    score_in: int,
    score_out: int,
    risk: float,
    action: str,
) -> None:
    """Enregistre la modulation pour l'audit et le rollback automatique."""
    _modulation_history.append({
        "sym":       sym,
        "score_in":  score_in,
        "score_out": score_out,
        "risk":      risk,
        "action":    action,
        "ts":        datetime.now(timezone.utc).timestamp(),
    })
    if len(_modulation_history) > 1000:
        _modulation_history[:] = _modulation_history[-500:]

    _check_rollback()


def _check_rollback() -> None:
    """Vérifie si la modulation dégrade le Sharpe → rollback automatique."""
    if not _fundamentals_active:
        return

    # Comparer score_in vs score_out sur les 20 dernières entrées
    recent = [m for m in _modulation_history if m["action"] != "pass"][-20:]
    if len(recent) < 20:
        return

    avg_in  = sum(m["score_in"]  for m in recent) / len(recent)
    avg_out = sum(m["score_out"] for m in recent) / len(recent)

    # Proxy Sharpe : si on réduit systématiquement les scores > 20% → rollback
    reduction_pct = (avg_in - avg_out) / max(avg_in, 1)
    if reduction_pct > FUNDAMENTALS_ROLLBACK_DELTA:
        force_disable(
            f"Rollback auto: réduction moyenne {reduction_pct:.0%} > seuil {FUNDAMENTALS_ROLLBACK_DELTA:.0%}"
        )


def get_modulation_stats() -> Dict[str, Any]:
    """Retourne les statistiques de modulation pour l'API."""
    total    = len(_modulation_history)
    blocked  = sum(1 for m in _modulation_history if m["action"] == "blocked")
    reduced  = sum(1 for m in _modulation_history if m["action"] == "reduced")
    passed   = sum(1 for m in _modulation_history if m["action"] == "pass")
    return {
        "active":   _fundamentals_active,
        "total":    total,
        "blocked":  blocked,
        "reduced":  reduced,
        "passed":   passed,
        "block_pct": round(blocked / total * 100, 1) if total else 0,
    }
