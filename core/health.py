"""core/health.py — santé & observabilité de la pyramide (N0). Réorg Phase 2 (27/07/2026).

`health_snapshot()` agrège l'état RÉEL de chaque niveau : socle (journal non censuré), pôles
N2 (online/degraded/offline), fusion N3 (dernier cycle : latence, erreurs), risque N4, exécution
N5 (positions démo, equity), fraîcheur des données, CPU/RAM (si psutil dispo). Sert la route
`GET /health`. Lecture seule ; imports métier PARESSEUX (invariant #6 : pas de cycle au load)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict


def _confluence() -> Dict[str, Any]:
    """État de la boucle de fusion N3 (heartbeat + pôles) — best-effort."""
    out = {"status": "offline", "heartbeat": None, "poles": {}, "symbols_tracked": 0}
    try:
        from fusion.confluence_demo_engine import HEARTBEAT, status_snapshot
        out["heartbeat"] = dict(HEARTBEAT)
        snap = status_snapshot() or {}
        syms = snap.get("symbols") or {}
        out["symbols_tracked"] = len(syms)
        # dernier cycle récent ⇒ online
        hb = HEARTBEAT or {}
        last = hb.get("last_cycle_at")
        if last:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            out["status"] = "online" if (age < 900 and hb.get("last_cycle_ok")) else "degraded"
            out["last_cycle_age_s"] = round(age, 1)
        # agrège le pole_status vu par le dernier state (si présent dans les résumés)
        poles = {}
        for s in list(syms.values())[:50]:
            for p, st in (s.get("pole_status") or {}).items():
                poles[p] = st
        out["poles"] = poles
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)
    return out


def _journal() -> Dict[str, Any]:
    """Socle N0 : volumes du journal non censuré."""
    try:
        from core.journal import get_journal
        return {"status": "online", "counts": get_journal().counts_by_kind()}
    except Exception as e:  # noqa: BLE001
        return {"status": "offline", "error": repr(e)}


def _execution() -> Dict[str, Any]:
    """N5 : positions démo + equity (via MT5, best-effort, ne bloque jamais)."""
    out = {"status": "unknown"}
    try:
        import MetaTrader5 as mt5
        from ingestion.market.mt5_provider import ensure_init, mt5_lock
        if not ensure_init():
            return {"status": "offline", "detail": "MT5 non initialisé"}
        with mt5_lock:
            acc = mt5.account_info()
            pos = mt5.positions_get() or []
        if acc is not None:
            out = {"status": "online", "login": acc.login, "equity": round(acc.equity, 2),
                   "balance": round(acc.balance, 2), "floating_pnl": round(acc.profit, 2),
                   "open_positions": len(pos), "demo": bool(int(acc.login) != 60261188)}
    except Exception as e:  # noqa: BLE001
        out = {"status": "offline", "error": repr(e)}
    return out


def _resources() -> Dict[str, Any]:
    try:
        import psutil  # optionnel
        return {"cpu_pct": psutil.cpu_percent(interval=0.0),
                "ram_free_mo": round(psutil.virtual_memory().available / 1e6),
                "disk_free_go": round(psutil.disk_usage(".").free / 1e9, 1)}
    except Exception:
        return {"note": "psutil absent — métriques CPU/RAM indisponibles"}


def _riskgate() -> Dict[str, Any]:
    """N4 : le RiskGate est-il présent, et câblé ? (shadow tant qu'aucun runtime ne l'importe)."""
    try:
        import importlib.util as _u
        present = _u.find_spec("risk.riskgate") is not None
        # câblé si un module runtime l'importe (heuristique : non, en Phase 1)
        return {"status": "shadow" if present else "absent", "wired": False}
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "error": repr(e)}


def health_snapshot() -> Dict[str, Any]:
    """Instantané de santé de toute la pyramide. Jamais bloquant."""
    t0 = time.monotonic()
    snap = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "socle_journal": _journal(),          # N0
        "fusion": _confluence(),              # N3 (+ pôles N2)
        "risk": _riskgate(),                  # N4
        "execution": _execution(),            # N5
        "resources": _resources(),
    }
    # verdict global simple
    problems = []
    if snap["fusion"].get("status") == "offline":
        problems.append("fusion hors-ligne")
    if snap["fusion"].get("heartbeat", {}).get("n_errors"):
        problems.append(f"erreurs cycle={snap['fusion']['heartbeat']['n_errors']}")
    ex = snap["execution"]
    if ex.get("status") == "online" and not ex.get("demo", True):
        problems.append("⚠️ COMPTE NON DÉMO")
    snap["overall"] = "ok" if not problems else "degraded"
    snap["problems"] = problems
    snap["build_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return snap
