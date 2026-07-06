"""execution/guards.py — Pipeline de guards pré-exécution (point de passage unique).

Tout ordre passe par run_guards() avant d'être transmis au broker/paper engine
(appelé depuis execution/executor.py::PaperExecutor.execute()).

Fail-safe : une garde qui ne peut pas s'évaluer BLOQUE (elle ne force jamais un trade).
Les gardes déjà couvertes ailleurs ne sont pas dupliquées ici :
  - cooldown entre signaux → execution/signal_manager.py::emit_signal()
  - taille de position / exposition max → execution/paper_trading.py::PaperEngine.open_position()
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from utils.config import (
    SYMBOLS, SYM_CLUSTER,
    GUARD_CORRELATED_EXPOSURE_ENABLED, GUARD_CORRELATED_EXPOSURE_MAX_PCT,
    GUARD_BLACKOUT_ENABLED, BLACKOUT_EVENTS_FILE,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GuardResult:
    passed: bool
    guard: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "guard": self.guard, "reason": self.reason}


_PASS = GuardResult(passed=True)


def _guard_stop_loss(signal: Dict[str, Any]) -> GuardResult:
    """Refuse tout ordre sans stop-loss valide."""
    sl = signal.get("sl", 0)
    if not sl or sl <= 0:
        return GuardResult(False, "stop_loss_required", "signal sans stop-loss valide")
    return _PASS


def _guard_whitelist(sym: str) -> GuardResult:
    if sym not in SYMBOLS:
        return GuardResult(False, "symbol_whitelist", f"{sym} hors whitelist ({SYMBOLS})")
    return _PASS


def _cluster_exposure_pct(sym: str, open_positions: Dict[str, float], capital: float) -> float:
    """Exposition cumulée (USDT) du cluster de `sym` parmi les positions ouvertes, en % du capital."""
    if capital <= 0:
        return 0.0
    cluster = SYM_CLUSTER.get(sym, sym)
    total = sum(
        size for s, size in open_positions.items()
        if SYM_CLUSTER.get(s, s) == cluster
    )
    return total / capital


def _guard_correlated_exposure(sym: str, open_positions: Dict[str, float], capital: float) -> GuardResult:
    if not GUARD_CORRELATED_EXPOSURE_ENABLED:
        return _PASS
    pct = _cluster_exposure_pct(sym, open_positions, capital)
    if pct > GUARD_CORRELATED_EXPOSURE_MAX_PCT:
        return GuardResult(
            False, "correlated_exposure",
            f"cluster {SYM_CLUSTER.get(sym, sym)} exposé à {pct:.0%} > seuil {GUARD_CORRELATED_EXPOSURE_MAX_PCT:.0%}",
        )
    return _PASS


_blackout_cache: Optional[list] = None
_blackout_cache_error = False


def _load_blackout_events() -> Optional[list]:
    """Charge config/blackout_events.json. Retourne None si illisible (distinct de liste vide)."""
    global _blackout_cache, _blackout_cache_error
    if _blackout_cache is not None or _blackout_cache_error:
        return _blackout_cache if not _blackout_cache_error else None
    try:
        if BLACKOUT_EVENTS_FILE.exists():
            _blackout_cache = json.loads(BLACKOUT_EVENTS_FILE.read_text(encoding="utf-8"))
        else:
            _blackout_cache = []
    except Exception as e:
        logger.warning("[GUARD] blackout_events illisible (%s) — fail-safe: bloque", e)
        _blackout_cache_error = True
        return None
    return _blackout_cache


def _guard_blackout(sym: str) -> GuardResult:
    if not GUARD_BLACKOUT_ENABLED:
        return _PASS
    events = _load_blackout_events()
    if events is None:
        return GuardResult(False, "event_blackout", "config blackout illisible — fail-safe")
    now = datetime.now(timezone.utc)
    for ev in events:
        if ev.get("symbol") not in (sym, "*"):
            continue
        try:
            start = datetime.fromisoformat(ev["start_iso"])
            end = datetime.fromisoformat(ev["end_iso"])
        except Exception:
            return GuardResult(False, "event_blackout", f"événement blackout mal formé: {ev}")
        if start <= now <= end:
            return GuardResult(False, "event_blackout", f"blackout actif: {ev.get('label', '')}")
    return _PASS


def run_guards(
    signal: Dict[str, Any],
    sym: str,
    open_positions: Optional[Dict[str, float]] = None,
    capital: float = 0.0,
) -> GuardResult:
    """Évalue toutes les gardes dans l'ordre, avant tout envoi d'ordre.

    `open_positions` : dict {symbol: size_usdt courant} des positions déjà ouvertes
    (utilisé par la garde d'exposition corrélée). `capital` : equity courante.

    Fail-safe : toute exception pendant l'évaluation d'une garde bloque l'ordre —
    une garde ne peut jamais forcer un trade, seulement le refuser.
    """
    open_positions = open_positions or {}
    checks = (
        ("stop_loss_required",  lambda: _guard_stop_loss(signal)),
        ("symbol_whitelist",    lambda: _guard_whitelist(sym)),
        ("correlated_exposure", lambda: _guard_correlated_exposure(sym, open_positions, capital)),
        ("event_blackout",      lambda: _guard_blackout(sym)),
    )
    from utils.event_bus import emit as _emit_event

    for name, check in checks:
        try:
            result = check()
        except Exception as e:
            logger.error("[GUARD] %s — erreur d'évaluation, bloqué par fail-safe: %s", name, e)
            result = GuardResult(False, f"guard_eval_error:{name}", str(e))
            _emit_event("GUARD", {"symbol": sym, "passed": False, **result.to_dict()})
            return result
        if not result.passed:
            logger.warning("[GUARD] %s refusé — %s: %s", sym, result.guard, result.reason)
            _emit_event("GUARD", {"symbol": sym, "passed": False, **result.to_dict()})
            return result
    _emit_event("GUARD", {"symbol": sym, "passed": True, "guard": "", "reason": ""})
    return GuardResult(True, "", "")
