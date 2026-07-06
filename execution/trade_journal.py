"""execution/trade_journal.py — Journal de trades "Trading-as-Git".

Storage : TRADE_JOURNAL_FILE (data/trade_journal.jsonl), append-only — jamais réécrit.
Chaque ligne est un événement référençant un `hash` de trade (staged/committed/rejected/
closed/approved). L'état courant d'un trade se reconstruit en rejouant le journal,
comme `git log`/`git show`.

JOURNAL_STAGING_ENABLED=0 (défaut) : stage() puis commit()/reject() sont appelés en
séquence immédiate par execution/executor.py — comportement d'exécution inchangé, seul
le format de stockage (append-only, hashé) change par rapport au logging plat existant.

JOURNAL_STAGING_ENABLED=1 : un trade reste "staged" tant qu'il n'est pas approuvé —
automatiquement si JOURNAL_AUTO_APPROVE=1 (et guards passés), sinon manuellement via
POST /journal/{hash}/approve (Phase D) qui appelle executor.execute_approved(hash).
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.config import TRADE_JOURNAL_FILE, JOURNAL_STAGING_ENABLED
from utils.logger import get_logger

logger = get_logger(__name__)

# Signaux en attente d'approbation manuelle (JOURNAL_STAGING_ENABLED=1 uniquement).
# En mémoire — perdu au redémarrage, comme les autres états transitoires du process.
_pending_signals: Dict[str, Dict[str, Any]] = {}

_STATUS_FROM_EVENT = {
    "staged": "staged", "approved": "approved", "committed": "filled",
    "rejected": "rejected", "closed": "closed",
}


def _append(event: Dict[str, Any]) -> None:
    """Ajoute une ligne au journal — jamais de réécriture, seulement des appends."""
    TRADE_JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRADE_JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def stage(signal: Dict[str, Any], spectral_features: Optional[Any] = None) -> str:
    """Stage un trade proposé — retourne un hash 8 caractères identifiant le trade."""
    h = uuid.uuid4().hex[:8]
    rationale: Dict[str, Any] = {
        "score":     signal.get("score"),
        "score_max": signal.get("score_max"),
        "confs":     signal.get("confs", []),
        "regime":    signal.get("regime"),
    }
    if spectral_features is not None:
        rationale["spectral"] = (
            spectral_features.to_dict() if hasattr(spectral_features, "to_dict") else spectral_features
        )
    _append({
        "hash": h, "event": "staged", "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": signal.get("symbol"), "side": signal.get("side"),
        "rationale": rationale,
    })
    if JOURNAL_STAGING_ENABLED:
        _pending_signals[h] = signal
    return h


def commit(h: str, position: Dict[str, Any]) -> None:
    _append({
        "hash": h, "event": "committed", "ts": datetime.now(timezone.utc).isoformat(),
        "position": position,
    })


def reject(h: str, reason: str) -> None:
    _append({
        "hash": h, "event": "rejected", "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    })


def close(h: str, exit_info: Dict[str, Any]) -> None:
    _append({
        "hash": h, "event": "closed", "ts": datetime.now(timezone.utc).isoformat(),
        "exit": exit_info,
    })


def mark_approved(h: str) -> None:
    _append({"hash": h, "event": "approved", "ts": datetime.now(timezone.utc).isoformat()})


def pop_pending(h: str) -> Optional[Dict[str, Any]]:
    """Retire et retourne le signal en attente d'approbation pour ce hash, si présent."""
    return _pending_signals.pop(h, None)


def _read_events() -> List[Dict[str, Any]]:
    if not TRADE_JOURNAL_FILE.exists():
        return []
    events: List[Dict[str, Any]] = []
    with TRADE_JOURNAL_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def get_journal(limit: int = 100) -> List[Dict[str, Any]]:
    """Reconstruit l'état courant de chaque trade en rejouant le journal (plus récent d'abord)."""
    by_hash: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for ev in _read_events():
        h = ev.get("hash")
        if h is None:
            continue
        if h not in by_hash:
            by_hash[h] = {"hash": h}
            order.append(h)
        trade = by_hash[h]
        event = ev.get("event")
        trade["status"] = _STATUS_FROM_EVENT.get(event, trade.get("status", event))
        if event == "staged":
            trade["ts_staged"] = ev.get("ts")
            trade["symbol"]    = ev.get("symbol")
            trade["side"]      = ev.get("side")
            trade["rationale"] = ev.get("rationale")
        elif event == "committed":
            trade["position"]     = ev.get("position")
            trade["ts_committed"] = ev.get("ts")
        elif event == "rejected":
            trade["reason"]      = ev.get("reason")
            trade["ts_rejected"] = ev.get("ts")
        elif event == "closed":
            trade["exit"]      = ev.get("exit")
            trade["ts_closed"] = ev.get("ts")
    trades = [by_hash[h] for h in reversed(order)]
    return trades[:limit]
