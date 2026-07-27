"""core/cortex.py — CORTEX : état projeté UNIFIÉ, lecture seule (axe E0 de l'audit archi).

Un point de lecture UNIQUE qui agrège l'état courant de tous les moteurs (confluence,
consensus, lead/lag, …) + une synthèse de santé. C'est le plan « état projeté » de
l'architecture 4-plans (Codex) : le cerveau (Hermes) et les dashboards lisent ICI, au lieu
d'interroger chaque store éparpillé.

⚠️ LECTURE SEULE / PRÉ-M2. Le cortex ne DÉCIDE rien, n'exécute rien, n'a aucun effet de bord :
il projette l'état déjà calculé par les boucles (aucun appel MT5/réseau lourd ici). FAIL-SAFE :
une source en échec ne casse pas le snapshot.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict

# verify_integrity() re-hache TOUT le journal, flux par flux : c'est un AUDIT,
# pas une sonde. Le cockpit interroge le cortex toutes les 5 s — sans ce cache
# l'audit complet tournait 12 fois par minute et pesait ~22 % du CPU du worker.
_INTEGRITE_TTL = 600.0
_integrite_verrou = threading.Lock()
_integrite_cache: Dict[str, object] = {"at": 0.0, "rapport": None}


def integrite_journal(force: bool = False) -> dict:
    """Rapport d'intégrité de l'EventPlane, ré-audité au plus toutes les 10 min.

    Le rapport porte son âge : un cache muet passerait pour une vérification
    fraîche alors qu'il ne prouve plus rien.
    """
    from core.event_plane import get_event_plane

    with _integrite_verrou:
        at = float(_integrite_cache["at"] or 0.0)
        rapport = _integrite_cache["rapport"]
    if force or rapport is None or (time.time() - at) > _INTEGRITE_TTL:
        rapport = get_event_plane().verify_integrity()
        at = time.time()
        with _integrite_verrou:
            _integrite_cache.update(at=at, rapport=rapport)
    return dict(rapport, verifie_il_y_a_s=round(time.time() - at, 1))


def _safe(fn: Callable) -> dict:
    try:
        return fn() or {}
    except Exception as exc:  # noqa: BLE001 — une source morte ne casse pas le cortex
        return {"error": repr(exc)}


def _confluence() -> dict:
    from core.confluence_demo_engine import status_snapshot
    return status_snapshot()


def _consensus() -> dict:
    from core.consensus_engine import status_snapshot
    return status_snapshot()


def _leadlag() -> dict:
    from core.lead_lag_engine import status_snapshot
    return status_snapshot()


def _eventplane() -> dict:
    from core.event_plane import get_event_plane
    plane = get_event_plane()
    health = plane.health()
    health["integrity"] = integrite_journal()
    return health


def _emotion() -> dict:
    """ÉMOTION comme ORGANE du cortex (demande Florent 21/07/2026 : « l'émotion doit
    principalement être intégrée au cortex neuronal »). Elle est UNE PIÈCE du noyau de
    calcul, pas le pilier décisionnaire : elle agit sur la décision à travers les familles
    du consensus, et le cortex la rend simplement VISIBLE.

    On projette l'émotion DÉJÀ CALCULÉE par la boucle de consensus — aucun appel MT5/réseau
    ici, le cortex doit rester léger (contrat du module)."""
    from core.consensus_engine import status_snapshot
    syms = (status_snapshot() or {}).get("symbols") or {}
    votes = {"long": 0, "short": 0, "neutral": 0}
    confs = []
    for s in syms.values():
        d = int((s.get("engine_directions") or {}).get("emotion") or 0)
        votes["long" if d > 0 else ("short" if d < 0 else "neutral")] += 1
        c = ((s.get("engine_confirmation") or {}).get("emotion") or {}).get("confidence")
        if isinstance(c, (int, float)):
            confs.append(float(c))
    return {"n_symbols": len(syms), "directions": votes, "confidences": confs}


def _summarize(name: str, snap: dict) -> dict:
    """Synthèse compacte + santé d'un moteur (pour la vue d'ensemble du cortex)."""
    if "error" in snap:
        return {"health": "down", "detail": snap["error"]}
    if name == "confluence":
        hb = snap.get("heartbeat") or {}
        syms = snap.get("symbols") or {}
        n_aggr = sum(1 for s in syms.values() if (s.get("aggressive") or {}).get("ready"))
        return {"health": "ok" if hb.get("last_cycle_ok") else "stale",
                "last_cycle_at": hb.get("last_cycle_at"), "n_symbols": len(syms),
                "n_aggressive_ready": n_aggr, "n_errors": hb.get("n_errors")}
    if name == "consensus":
        heartbeat = snap.get("heartbeat") or {}
        items = snap.get("symbols") or snap.get("by_symbol") or snap.get("assets") or snap.get("consensus") or {}
        n = len(items) if isinstance(items, (dict, list)) else 0
        last_cycle_at = heartbeat.get("last_cycle_at") or snap.get("ts")
        cycle_ok = heartbeat.get("last_cycle_ok", True)
        state = "ok" if last_cycle_at and cycle_ok else ("stale" if last_cycle_at else "cold")
        return {"health": state, "last_cycle_at": last_cycle_at, "n_assets": n,
                "m2_required": snap.get("m2_required", True),
                "decision_capability": snap.get("decision_capability", False)}
    if name == "leadlag":
        by_tf = snap.get("by_tf") or {}
        strong = sum(len((v or {}).get("strong", [])) for v in by_tf.values())
        return {"health": "ok" if snap.get("ts") else "cold",
                "timeframes": list(by_tf.keys()), "n_strong_candidates": strong,
                "note": "pré-M2, ne décide rien"}
    if name == "emotion":
        votes = snap.get("directions") or {}
        confs = snap.get("confidences") or []
        n = int(snap.get("n_symbols") or 0)
        directional = int(votes.get("long", 0)) + int(votes.get("short", 0))
        # `health` reflète le fonctionnement de l'ORGANE, pas son humeur du moment : une
        # émotion neutre n'est pas une panne. `expressive` dit si elle porte une direction.
        return {"health": "ok" if n else "cold",
                "expressive": directional > 0, "n_symbols": n,
                "n_directional": directional, "directions": votes,
                "mean_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
                "note": "une pièce du noyau de calcul, pas le pilier décisionnaire"}
    if name == "eventplane":
        integ = (snap.get("integrity") or {})
        integrity_ok = integ.get("ok")
        state = "ok" if integrity_ok is True else ("corrupt" if integrity_ok is False else "unknown")
        return {"health": state,
                "n_events": snap.get("n_events", 0), "head_offset": snap.get("last_offset", 0),
                "consumer_failures": snap.get("consumer_failures", 0),
                "transport_mode": snap.get("transport_mode")}
    return {"health": "ok"}


def snapshot(*, full: bool = False) -> dict:
    """État projeté unifié. `full=False` → synthèses de santé (léger, pour vue d'ensemble) ;
    `full=True` → snapshots complets de chaque moteur. LECTURE SEULE, fail-safe."""
    sources: Dict[str, Callable] = {
        "confluence": _confluence, "consensus": _consensus, "leadlag": _leadlag,
        "emotion": _emotion, "eventplane": _eventplane,
    }
    raw = {name: _safe(fn) for name, fn in sources.items()}
    health = {name: _summarize(name, snap) for name, snap in raw.items()}
    overall = "ok" if all(h.get("health") == "ok" for h in health.values()) else "degraded"
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall_health": overall,
        "engines": health,
        "note": "CORTEX lecture seule (plan « état projeté ») — ne décide rien, pré-M2.",
    }
    if full:
        out["detail"] = raw
    return out
