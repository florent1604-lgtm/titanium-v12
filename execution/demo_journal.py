"""execution/demo_journal.py — Journal des tentatives d'ordre DÉMO (v12, 15/07/2026).

Décision Florent (15/07/2026) : « chaque simulation doit être écrite et nous
apprendre » — on recentre tout sur le compte DÉMO MT5, c'est lui qui fait foi.

Or rien n'enregistrait les tentatives : l'exécuteur renvoyait {sent, reason, …}
et le résultat se perdait dans un log. Ce module persiste CHAQUE tentative —
acceptée ET refusée, avec sa raison — en NDJSON append-only.

Pourquoi les refus comptent autant que les envois : « 0 trade » n'est pas une
information ; « 14 refus dont 12 ALREADY_OPEN et 2 RISK_LOW_MARGIN » en est une.
C'est ce qui nous a coûté deux jours à comprendre le cluster saturé.

ÉMOTION EN OBSERVATION : on joint l'état émotionnel lu à l'instant de la
décision, SANS qu'il l'influence (le segment reste read-only, M2 avant tout usage
décisionnel). C'est le seul moyen de mesurer PLUS TARD si l'émotion aurait aidé,
au lieu de le parier. Chaque ligne du journal est une observation appariée
{ce que le bot a fait} × {ce que la foule ressentait}.

NON FATAL par construction : journaliser ne doit JAMAIS casser un ordre. Toute
erreur ici est avalée et loggée — le trading passe avant la traçabilité.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "data" / "demo_journal.ndjson"


def _emotion_snapshot(symbol: str) -> Optional[dict]:
    """État émotionnel au moment de la décision — OBSERVATION SEULE.
    Fail-safe absolu : si l'émotion casse, l'ordre part quand même."""
    try:
        from emotion.market_context import emotion_for
        st = emotion_for(symbol)
        if not st.available:
            return {"available": False}
        return {
            "available": True, "label": st.label,
            "valence": st.valence, "arousal": st.arousal, "momentum": st.momentum,
            "confidence": st.confidence, "stale": st.stale,
            # Ce que l'émotion AURAIT dit si on l'avait écoutée (jamais appliqué) :
            "would_block": st.filter_block, "would_fade": st.contrarian_bias,
            "sources": sorted((st.breakdown or {}).keys()),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DEMO-JOURNAL] émotion indisponible %s: %r", symbol, exc)
        return {"available": False, "error": type(exc).__name__}


def record(symbol: str, side: str, result: Optional[dict], *,
           atr: float | None = None, engine: str = "?",
           with_emotion: bool = True) -> None:
    """Écrit une tentative d'ordre démo. N'échoue JAMAIS vers l'appelant."""
    try:
        res = result or {}
        row: dict[str, Any] = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "engine": engine, "symbol": symbol, "side": side,
            "sent": bool(res.get("sent")),
            "reason": res.get("reason"),
            "lot": res.get("lot"), "price": res.get("price"),
            "sl": res.get("sl"), "tp": res.get("tp"),
            "ticket": res.get("ticket"),
            "risk_money": res.get("risk_money"),
            "atr": atr,
        }
        acc = res.get("account") or {}
        if isinstance(acc, dict):
            row["equity"] = acc.get("equity")
            row["login"] = acc.get("login")
        if with_emotion:
            row["emotion_observed"] = _emotion_snapshot(symbol)

        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DEMO-JOURNAL] écriture impossible %s: %r", symbol, exc)


def read_all() -> list[dict]:
    """Toutes les tentatives journalisées (lignes corrompues ignorées)."""
    if not JOURNAL.exists():
        return []
    rows = []
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summary() -> dict:
    """Bilan : envoyés / refusés par raison. C'est le « pourquoi 0 trade »."""
    rows = read_all()
    sent = [r for r in rows if r.get("sent")]
    refused = [r for r in rows if not r.get("sent")]
    by_reason: dict[str, int] = {}
    for r in refused:
        key = str(r.get("reason") or "?").split(":")[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    return {
        "attempts": len(rows), "sent": len(sent), "refused": len(refused),
        "refused_by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "symbols": sorted({str(r.get("symbol")) for r in rows}),
        "first": rows[0]["ts_utc"] if rows else None,
        "last": rows[-1]["ts_utc"] if rows else None,
    }
