"""core/cloe/confidence.py — INDICE DE CONFIANCE de Cloe (modulateur de lot). Florent 27/07.

« Le lot doit être proportionnel à la prise de RISQUE ; l'indice de confiance basé sur les
analyses de Cloe adapte cela selon les conditions. »

`confidence_for(...)` renvoie une confiance ∈ [0.2, 1.0] pour un CONTEXTE (actif/catégorie,
sens, nb de piliers, régime) à partir de la PERFORMANCE MESURÉE de ce contexte (data/
trade_analytics.json — P&L RÉEL, donc NET DES COÛTS). Un contexte gagnant → confiance haute →
gros lot ; un contexte où le coût tue l'edge → perf négative → confiance basse → petit lot.
Le coût entre ainsi INDIRECTEMENT (via la perf mesurée), jamais dans la formule du lot.

Neutre 0.5 quand pas de donnée. Cache TTL. Socle N0, aucun import métier lourd.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
_TA = _ROOT / "data" / "trade_analytics.json"
_CRYPTO = {"BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "SOL", "DOGE", "BNB", "AVAX", "UNI", "COMP", "MANA", "XTZ"}

_LOW, _HIGH, _NEUTRAL = 0.2, 1.0, 0.5
_K = 0.15                                     # sensibilité espérance(R) → confiance
_lock = threading.Lock()
_cache = {"ts": 0.0, "agg": None}


def _category(sym: str) -> str:
    s = str(sym or "").upper()
    if any(s.startswith(c) and (s.endswith("USD") or s.endswith("-USD")) for c in _CRYPTO):
        return "crypto"
    if s.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "metals"
    if s.endswith(".FS"):
        return "futures"
    if len(s) == 6 and s.isalpha():
        return "fx"
    return "index/cash"


def _structure(n) -> Optional[str]:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return {0: "0", 1: "S(1p)", 2: "S(2p)", 3: "M(3p)", 4: "L(4p)", 5: "XL(5p)"}.get(n,
            "XL(5p)" if n > 5 else None)


def _aggregates(ttl: float = 30.0):
    now = time.monotonic()
    with _lock:
        if _cache["agg"] is not None and (now - _cache["ts"]) < ttl:
            return _cache["agg"]
    agg = None
    try:
        agg = json.loads(_TA.read_text(encoding="utf-8")).get("aggregates", {})
    except Exception:
        agg = {}
    with _lock:
        _cache["agg"], _cache["ts"] = agg, now
    return agg


def _dim_conf(rows, key, value) -> Optional[float]:
    """Confiance d'une dimension = espérance(R) mesurée, rétrécie vers neutre si peu d'échantillon."""
    if not rows or value is None:
        return None
    for r in rows:
        if str(r.get(key)) == str(value):
            exp = r.get("expectancy_R")
            n = int(r.get("n") or 0)
            if exp is None or n < 3:
                return None
            raw = _NEUTRAL + float(exp) * _K
            shrink = min(n, 30) / 30.0                     # peu de trades → proche de neutre
            conf = _NEUTRAL + (raw - _NEUTRAL) * shrink
            return max(_LOW, min(_HIGH, conf))
    return None


def confidence_for(symbol: str, side: int, n_pillars=None, regime: Optional[str] = None) -> float:
    """Confiance ∈ [0.2, 1.0] pour ce contexte, d'après la perf mesurée (nette de coûts)."""
    agg = _aggregates()
    if not agg:
        return _NEUTRAL
    side_s = "long" if int(side or 0) > 0 else "short"
    parts = []
    for c in (_dim_conf(agg.get("category"), "category", _category(symbol)),
              _dim_conf(agg.get("side"), "side", side_s),
              _dim_conf(agg.get("structure"), "structure", _structure(n_pillars)),
              _dim_conf(agg.get("symbol"), "symbol", symbol)):
        if c is not None:
            parts.append(c)
    if not parts:
        return _NEUTRAL
    return round(sum(parts) / len(parts), 4)               # moyenne des dimensions disponibles
