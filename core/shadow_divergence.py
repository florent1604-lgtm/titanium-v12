"""core/shadow_divergence.py — Lot C (M2-1) : observateur SHADOW signal <-> gate.

OBSERVATION PURE, contrefactuelle. Ce module NE décide rien, NE trade rien, NE
modifie AUCUN état de trading. Pour chaque signal directionnel candidat de
``signal_engine``, il calcule ce que ``core.brain_gate.gate_entry`` DIRAIT
(verdict du cerveau : consensus + master + régime géométrique) et journalise
l'ACCORD ou le DÉSACCORD avec la décision réelle d'émission.

But (protocole M2, étape 1 « non exécutionnelle ») : PROUVER et MESURER la
divergence entre le chemin crypto (signal_engine, qui n'appelle pas le cerveau)
et le contrat de décision unifié (brain_gate) — AVANT tout câblage. Les preuves
s'accumulent dans ``data/shadow_divergence.ndjson`` et se dépouillent avec
``divergence_summary()``.

Garde-fou ABSOLU : toute exception est avalée (fail-safe). L'observateur ne peut
jamais lever dans la boucle de scan ni ralentir/altérer une émission. Si le
cerveau est illisible, on journalise l'échec et on continue — zéro impact.

Câblage attendu (côté signal_engine.py, édition de Copilot, 2 lignes additives
après ``emit_signal`` l.256) ::

    try:
        from core.shadow_divergence import observe
        observe(sym, side, effective_score, emitted=bool(signal),
                score_min=SCORE_MIN_REQUIRED)
    except Exception:
        pass

Idéalement l'appel est déporté via ``asyncio.to_thread(observe, ...)`` pour ne
pas bloquer l'event-loop (gate_entry lit de petits JSON sur disque).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# Mapping des sens « métier » de signal_engine vers l'entier attendu par gate_entry.
_SIDE_MAP = {
    "ACHAT": 1, "BUY": 1, "LONG": 1,
    "VENTE": -1, "SELL": -1, "SHORT": -1,
}

_JOURNAL = os.path.join("data", "shadow_divergence.ndjson")
_LOCK = threading.Lock()


def _proposed_side(side: Any) -> int:
    """'ACHAT'/'VENTE'/int/... -> {+1,-1,0}. Tout ce qui n'est pas directionnel -> 0."""
    if isinstance(side, (int, float)):
        return 1 if side > 0 else (-1 if side < 0 else 0)
    return _SIDE_MAP.get(str(side).strip().upper(), 0)


def _classify(emitted: bool, proposed: int, brain_allow: bool, brain_side: int) -> str:
    """Étiquette de divergence entre la décision RÉELLE (emitted) et le verdict cerveau."""
    if emitted and not brain_allow:
        return "EMIT_BUT_BRAIN_BLOCK"          # le signal part, le cerveau bloquerait
    if emitted and brain_allow and brain_side == -proposed:
        return "EMIT_BUT_BRAIN_OPPOSITE"        # le signal part, le cerveau va à l'inverse
    if (not emitted) and brain_allow:
        return "NOEMIT_BUT_BRAIN_ALLOW"         # rien émis, le cerveau aurait laissé passer
    if emitted and brain_allow:
        return "AGREE_ALLOW"
    return "AGREE_BLOCK"                         # rien émis, le cerveau bloquerait aussi


def observe(symbol: str, side: Any, effective_score: Any, *,
            emitted: bool, score_min: Optional[float] = None,
            extra: Optional[dict] = None) -> Optional[str]:
    """Journalise le contrefactuel cerveau pour un candidat de signal_engine.

    NE LÈVE JAMAIS. Retourne l'étiquette de divergence (ou None si non applicable
    / erreur avalée) — utile en test, ignoré en prod.

    Args:
        symbol: instrument (ex. "BTCUSDT").
        side: sens proposé par le scan ("ACHAT"/"VENTE"/int/...).
        effective_score: score après filtres macro/momentum (0 = neutralisé).
        emitted: décision RÉELLE — un signal a-t-il effectivement été émis ?
        score_min: seuil courant, journalisé pour contextualiser (facultatif).
        extra: métadonnées facultatives (ex. {"risk_factor": ...}).
    """
    try:
        proposed = _proposed_side(side)
        if proposed == 0:
            return None  # rien de directionnel à comparer

        # Verdict contrefactuel du cerveau — lecture seule, aucun effet de bord trading.
        from core.brain_gate import gate_entry
        gate = gate_entry(symbol, proposed)
        brain_allow = bool(getattr(gate, "allow", False))
        brain_side = int(getattr(gate, "side", 0) or 0)
        reasons = list(getattr(gate, "reason_codes", ()) or ())

        divergence = _classify(bool(emitted), proposed, brain_allow, brain_side)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "proposed": proposed,
            "effective_score": effective_score,
            "score_min": score_min,
            "emitted": bool(emitted),
            "brain_allow": brain_allow,
            "brain_side": brain_side,
            "brain_conviction": float(getattr(gate, "conviction", 0.0) or 0.0),
            "reason_codes": reasons,
            "divergence": divergence,
        }
        if extra:
            record["extra"] = extra

        line = json.dumps(record, ensure_ascii=False)
        with _LOCK:
            with open(_JOURNAL, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return divergence
    except Exception as exc:  # noqa: BLE001 — fail-safe ABSOLU
        logger.debug("[SHADOW] observe(%s) non bloquant: %s", symbol, exc)
        return None


def divergence_summary(path: Optional[str] = None) -> dict:
    """Dépouille le journal : compte par étiquette + taux de désaccord.

    Lecture seule, tolérante aux lignes corrompues. Pour usage CLI / route de
    lecture / dépouillement M2 — pas appelé dans la boucle de scan.
    """
    p = path or _JOURNAL
    counts: dict[str, int] = {}
    total = 0
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                label = str(rec.get("divergence", "UNKNOWN"))
                counts[label] = counts.get(label, 0) + 1
                total += 1
    except FileNotFoundError:
        return {"total": 0, "counts": {}, "disagreement_rate": 0.0}

    disagreements = sum(
        n for lbl, n in counts.items() if lbl.startswith("EMIT_BUT_") or lbl == "NOEMIT_BUT_BRAIN_ALLOW"
    )
    rate = (disagreements / total) if total else 0.0
    return {"total": total, "counts": counts, "disagreement_rate": round(rate, 4)}
