"""execution/signal_manager.py — Validation et émission des signaux avec cooling period."""
from __future__ import annotations
import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from utils.config import SYMBOLS, get_sym_override, SCORE_MIN_REQUIRED, SIGNAL_COOLDOWN_SEC
from utils.logger import get_logger

logger = get_logger(__name__)

# État courant des signaux (partagé avec API/WS)
signals: Dict[str, Dict[str, Any]] = {s: {} for s in SYMBOLS}
_last_hash:        Dict[str, str]   = {s: "" for s in SYMBOLS}

# Cooling period — un seul signal actif par sens toutes les SIGNAL_COOLDOWN_SEC secondes
_last_signal_ts:   Dict[str, float] = {s: 0.0 for s in SYMBOLS}
_last_signal_side: Dict[str, str]   = {s: ""  for s in SYMBOLS}

# Circuit breaker — bloque les signaux quand actif
_circuit_breaker: Dict[str, bool] = {s: False for s in SYMBOLS}


def set_circuit_breaker(sym: str, active: bool, reason: str = "") -> None:
    """Active/désactive le circuit breaker pour un symbole."""
    prev = _circuit_breaker.get(sym, False)
    _circuit_breaker[sym] = active
    if active and not prev:
        logger.warning("[CB] %s CIRCUIT BREAKER actif — %s", sym, reason)
    elif not active and prev:
        logger.info("[CB] %s Circuit breaker désactivé", sym)


def is_circuit_breaker_active(sym: str) -> bool:
    return _circuit_breaker.get(sym, False)


def _state_hash(state: dict) -> str:
    """Hash rapide du state pour détecter les changements."""
    key = f"{state.get('score')}:{state.get('side')}:{state.get('price', 0):.2f}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _correlation_id() -> str:
    """Génère un correlation ID court pour chaque signal."""
    return uuid.uuid4().hex[:12]


def emit_signal(
    sym: str,
    score: int,
    side: str,
    confs: list,
    ctx: dict,
    levels: dict,
) -> Optional[Dict[str, Any]]:
    """Valide et émet un signal si le score dépasse le minimum requis.

    Cooling period : un signal ACHAT/VENTE ne peut pas être ré-émis dans le même sens
    avant SIGNAL_COOLDOWN_SEC secondes. Exception : si la direction change.

    Returns: signal dict si émis, None sinon.
    """
    score_min = get_sym_override(sym, "score_min", SCORE_MIN_REQUIRED)
    now = time.monotonic()

    if score < score_min or side == "NEUTRE":
        signals[sym] = {
            "symbol": sym,
            "score":  score,
            "side":   side,
            "active": False,
            "ts":     datetime.now(timezone.utc).isoformat(),
            **ctx,
        }
        return None

    # ── Circuit breaker ───────────────────────────────────────────────────────
    if _circuit_breaker.get(sym, False):
        logger.debug("[SIGNAL] %s bloqué — circuit breaker actif", sym)
        signals[sym] = {
            "symbol": sym, "score": score, "side": side,
            "active": False, "blocked_by": "circuit_breaker",
            "ts": datetime.now(timezone.utc).isoformat(), **ctx,
        }
        return None

    # ── Cooling period ────────────────────────────────────────────────────────
    elapsed   = now - _last_signal_ts[sym]
    same_side = (_last_signal_side[sym] == side)

    if same_side and elapsed < SIGNAL_COOLDOWN_SEC:
        remaining = int(SIGNAL_COOLDOWN_SEC - elapsed)
        logger.debug(
            "[SIGNAL] %s %s ignoré — cooling period (%ds restants)",
            sym, side, remaining,
        )
        # Met à jour l'état sans émettre (pour que le frontend voit le score live)
        signals[sym] = {
            "symbol": sym, "score": score, "side": side,
            "active": False, "cooling_remaining": remaining,
            "ts": datetime.now(timezone.utc).isoformat(), **ctx,
        }
        return None

    # ── Nouveau signal ou changement de direction ─────────────────────────────
    _last_signal_ts[sym]   = now
    _last_signal_side[sym] = side

    signal = {
        "symbol":        sym,
        "score":         score,
        "score_max":     11,
        "side":          side,
        "active":        True,
        "confs":         confs,
        "correlation_id": _correlation_id(),
        "ts":            datetime.now(timezone.utc).isoformat(),
        "price":         ctx.get("price", 0),
        "regime":        ctx.get("regime", "UNKNOWN"),
        "rsi":           ctx.get("rsi", 50),
        "adx":           ctx.get("adx", 0),
        "sl":            levels.get("sl", 0),
        "tp1":           levels.get("tp1", 0),
        "tp2":           levels.get("tp2", 0),
        "tp3":           levels.get("tp3", 0),
        "atr":           levels.get("atr", 0),
        "rr":            levels.get("rr", 0),
        **{k: v for k, v in ctx.items() if k not in ("price", "regime", "rsi", "adx")},
    }

    signals[sym] = signal
    logger.info(
        "[SIGNAL] %s %s score=%d/11 confs=%s cid=%s",
        sym, side, score, confs, signal["correlation_id"],
    )
    return signal


def has_changed(sym: str) -> bool:
    """Retourne True si le signal a changé depuis le dernier broadcast."""
    current_hash = _state_hash(signals.get(sym, {}))
    if current_hash != _last_hash[sym]:
        _last_hash[sym] = current_hash
        return True
    return False


def get_all_signals() -> Dict[str, Dict[str, Any]]:
    return dict(signals)
