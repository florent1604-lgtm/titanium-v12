"""core/brain_gate.py — PORTE NEURONALE d'entrée : le CERVEAU filtre, l'ÉMOTION dimensionne,
le MASTER (Florent) prime.

Ferme la boucle cœur → cerveau → redistribution, avec l'ÉMOTION comme MOTEUR DE CONVICTION
(choix de Florent). Flux :
  1. CŒUR : le réflexe structuré propose une entrée (sens `proposed_side`).
  2. CERVEAU : le consensus (croisement confluence + scoring + émotion) FILTRE — il bloque
     seulement s'il est en CONFLIT interne ou s'oppose au sens. Décisif, mais pas figé (on
     n'exige pas le seuil strict CONFIRMED qui bloquait tout).
  3. ÉMOTION : la peur/avidité pilote une CONVICTION ∈ [0,1] → un facteur de TAILLE.
     Alignée + forte = pleine taille ; tiède = réduite ; opposée = taille plancher.
  4. MASTER : Florent prime toujours (FORCE_LONG/FORCE_SHORT/BLOCK/PAUSE).

⚠️ Gouverne l'EXÉCUTION (placement démo). L'observation de tous les setups continue. Fail-safe :
cerveau illisible → pas de trade (sauf ordre master). PAPER/DEMO ONLY.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
_MASTER_PATH = _ROOT / "data" / "brain_master.json"
_GLOBAL_KEY = "*"

AUTO = "AUTO"
FORCE_LONG = "FORCE_LONG"
FORCE_SHORT = "FORCE_SHORT"
BLOCK = "BLOCK"
PAUSE = "PAUSE"
_MODES = {AUTO, FORCE_LONG, FORCE_SHORT, BLOCK, PAUSE}

_SIDE = {"long": 1, "short": -1, "neutral": 0}
_CONV_FLOOR = 0.20            # taille plancher (émotion opposée) — on n'annule pas, on réduit
_lock = threading.Lock()
_masters: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class BrainGate:
    """Décision de la porte. `allow` = on exécute ; `side` = sens effectif (+1/-1) ;
    `conviction` ∈ [0,1] = facteur de TAILLE (piloté par l'émotion) ; `source` = qui décide."""
    allow: bool
    side: int
    conviction: float
    source: str
    verdict: Optional[str]
    reason_codes: tuple


# --- Store des directives MASTER (persisté) ----------------------------------------------
def _load() -> Dict[str, str]:
    global _masters
    if _masters is not None:
        return _masters
    try:
        _masters = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))
        if not isinstance(_masters, dict):
            _masters = {}
    except (FileNotFoundError, ValueError):
        _masters = {}
    return _masters


def _persist() -> None:
    try:
        from utils.atomic_state import save_json_atomic
        save_json_atomic(_MASTER_PATH, _masters or {})
    except Exception:
        _MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MASTER_PATH.write_text(json.dumps(_masters or {}), encoding="utf-8")


def set_master(symbol: str, mode: str) -> Dict[str, str]:
    """Florent (master) pose/lève une directive sur un symbole (ou « * » global). AUTO efface."""
    mode = (mode or "").upper()
    if mode not in _MODES:
        raise ValueError(f"MODE_INVALIDE:{mode}")
    with _lock:
        m = _load()
        if mode == AUTO:
            m.pop(symbol, None)
        else:
            m[symbol] = mode
        _persist()
        return dict(m)


def get_master(symbol: str) -> str:
    m = _load()
    return m.get(symbol) or m.get(_GLOBAL_KEY) or AUTO


def all_masters() -> Dict[str, str]:
    return dict(_load())


def reset_cache() -> None:
    global _masters
    with _lock:
        _masters = None


# --- Le cerveau : verdict consensus (avec émotion embarquée) -----------------------------
def _consensus_lookup(symbol: str) -> Optional[dict]:
    try:
        from core.consensus_engine import LAST_RESULTS
        return LAST_RESULTS.get(symbol)
    except Exception:
        return None


def _conviction(cons: dict, side: int) -> tuple:
    """Conviction ∈ [0,1] pilotée par l'ÉMOTION (moteur principal) + la force technique.
    Retourne (conviction, emotion_reason). Alignée forte → ~1 ; tiède → moyenne ; opposée →
    plancher. L'émotion NE bloque pas (choix Florent : sizing, pas veto)."""
    try:
        cscore = abs(float(cons.get("consensus_score") or 0)) / 100.0
        coverage = float(cons.get("coverage") or 0.0)
    except (TypeError, ValueError):
        cscore = coverage = 0.0
    tech = max(0.0, min(1.0, coverage * cscore))              # force technique 0..1

    ed = cons.get("engine_directions") or {}
    ec = (cons.get("engine_confirmation") or {}).get("emotion") or {}
    emo_dir = int(ed.get("emotion") or 0)
    try:
        emo_conf = max(0.0, min(1.0, float(ec.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        emo_conf = 0.0
    if emo_dir == side and side != 0:
        emo_signed, tag = emo_conf, "EMO_ALIGNED"
    elif emo_dir == -side and side != 0:
        emo_signed, tag = -emo_conf, "EMO_OPPOSED"
    else:
        emo_signed, tag = 0.0, "EMO_NEUTRAL"
    # Émotion = levier principal (0.40) ; technique = appoint (0.30) ; socle 0.30.
    conv = 0.30 + 0.30 * tech + 0.40 * emo_signed
    return max(_CONV_FLOOR, min(1.0, conv)), tag


def gate_entry(symbol: str, proposed_side: int, *,
               consensus_fn: Optional[Callable] = None,
               master_fn: Optional[Callable] = None) -> BrainGate:
    """Décide si une entrée s'exécute + avec quelle CONVICTION (taille). Le MASTER prime ;
    sinon le CERVEAU filtre (bloque conflit/opposition) et l'ÉMOTION dimensionne."""
    getcons = consensus_fn or _consensus_lookup
    getmaster = master_fn or get_master

    # 1. MASTER — droit absolu de Florent (conviction pleine sur un ordre forcé).
    mode = (getmaster(symbol) or AUTO)
    if mode in (BLOCK, PAUSE):
        return BrainGate(False, 0, 0.0, "MASTER", None, (f"MASTER_{mode}",))
    if mode == FORCE_LONG:
        return BrainGate(True, 1, 1.0, "MASTER", None, ("MASTER_FORCE_LONG",))
    if mode == FORCE_SHORT:
        return BrainGate(True, -1, 1.0, "MASTER", None, ("MASTER_FORCE_SHORT",))

    # 2. AUTO → le CERVEAU filtre.
    cons = getcons(symbol)
    if not cons:
        return BrainGate(False, 0, 0.0, "BRAIN", None, ("BRAIN_NO_COVERAGE",))
    status = cons.get("status")
    if status in ("INSUFFICIENT", "ERROR", None):
        return BrainGate(False, 0, 0.0, "BRAIN", status, (f"BRAIN_{status or 'UNKNOWN'}",))
    cside = _SIDE.get(cons.get("side"), 0)
    side = proposed_side or cside                # sans réflexe, on suit le sens du cerveau
    if side == 0:
        return BrainGate(False, 0, 0.0, "BRAIN", status, ("BRAIN_NO_SIDE",))
    # Le cerveau BLOQUE s'il est en conflit interne ou s'oppose franchement au sens proposé.
    if bool(cons.get("conflict")) or status == "CONFLICT":
        return BrainGate(False, 0, 0.0, "BRAIN", status, ("BRAIN_CONFLICT",))
    if cside != 0 and cside == -side:
        return BrainGate(False, 0, 0.0, "BRAIN", status, ("BRAIN_SIDE_CONFLICT",))

    # 3. Autorisé — l'ÉMOTION pilote la conviction/taille.
    conv, emo_tag = _conviction(cons, side)
    return BrainGate(True, side, conv, "BRAIN", status, ("BRAIN_ALLOW", emo_tag))
