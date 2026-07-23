"""core/sr_levels.py — Niveaux de support/résistance explicites (multi-touches).

Brique n°1 de la méthode de Florent : les « gros niveaux S/R » lus sur TF hautes.
Le bot n'avait que l'EMA200 (tendance), pas de niveaux S/R comme objets.

On détecte les pivots (swing highs/lows), on CLUSTERISE les pivots proches en
niveaux, et on pondère par le NOMBRE DE TOUCHES (plus un niveau est retesté, plus
il est fort) + la récence. Un niveau confirmé par un nœud de volume (VPOC/HVN) est
encore plus fiable. Support = sous le prix, résistance = au-dessus.

API pure (numpy/pandas), sans look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    kind: str            # 'support' | 'resistance' (relatif au prix courant)
    strength: float      # 0..1 (touches + récence, + bonus volume)
    volume_confirmed: bool = False


def _pivots(highs, lows, k: int = 3):
    sh, sl = [], []
    n = len(highs)
    for i in range(k, n - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            sh.append((i, float(highs[i])))
        if lows[i] == min(lows[i - k:i + k + 1]):
            sl.append((i, float(lows[i])))
    return sh, sl


def _cluster(pivots, tol: float):
    """Regroupe les pivots dont les prix sont à < tol l'un de l'autre."""
    if not pivots:
        return []
    pts = sorted(pivots, key=lambda x: x[1])
    clusters = [[pts[0]]]
    for idx, price in pts[1:]:
        if abs(price - clusters[-1][-1][1]) <= tol:
            clusters[-1].append((idx, price))
        else:
            clusters.append([(idx, price)])
    return clusters


def compute_sr_levels(df: pd.DataFrame, *, k: int = 3, tol_pct: float = 0.4,
                      volume_profile=None) -> List[Level]:
    """Niveaux S/R clusterisés, pondérés par touches + récence. `volume_profile`
    optionnel (core.volume_profile.VolumeProfile) → bonus si aligné à un HVN."""
    if (not isinstance(k, (int, np.integer)) or k <= 0
            or not np.isfinite(tol_pct) or tol_pct <= 0 or df is None
            or len(df) < 2 * k + 5 or not {"high", "low"}.issubset(df.columns)):
        return []
    highs = df["high"].to_numpy(float); lows = df["low"].to_numpy(float)
    if (not np.isfinite(highs).all() or not np.isfinite(lows).all()
            or np.any(highs < lows)):
        return []
    n = len(highs)
    price_now = float(df["close"].iloc[-1]) if "close" in df.columns else float(highs[-1])
    if not np.isfinite(price_now) or price_now <= 0:
        return []
    tol = price_now * tol_pct / 100.0

    sh, sl = _pivots(highs, lows, k)
    levels: List[Level] = []
    hvns = list(getattr(volume_profile, "hvn", []) or [])

    for pivots in (sh, sl):
        for cl in _cluster(pivots, tol):
            price = float(np.mean([p for _, p in cl]))
            touches = len(cl)
            recency = max(idx for idx, _ in cl) / max(n - 1, 1)     # 0..1
            vol_ok = any(abs(price - h) <= tol for h in hvns)
            strength = min(1.0, 0.25 * touches + 0.35 * recency + (0.2 if vol_ok else 0.0))
            kind = "support" if price < price_now else "resistance"
            levels.append(Level(round(price, 8), touches, kind, round(strength, 3), vol_ok))

    return sorted(levels, key=lambda lv: -lv.strength)


def nearest(levels: List[Level], price: float, kind: Optional[str] = None) -> Optional[Level]:
    cand = [lv for lv in levels if kind is None or lv.kind == kind]
    return min(cand, key=lambda lv: abs(lv.price - price)) if cand else None


def entry_context(df: pd.DataFrame, price: float, *, k: int = 3,
                  volume_profile=None) -> dict:
    """Le prix est-il sur/proche d'un gros niveau (rebond probable) ?"""
    if not np.isfinite(price) or price <= 0:
        return {"available": False}
    levels = compute_sr_levels(df, k=k, volume_profile=volume_profile)
    if not levels:
        return {"available": False}
    tol = price * 0.4 / 100.0
    sup = nearest(levels, price, "support")
    res = nearest(levels, price, "resistance")
    on_level = next((lv for lv in levels if abs(lv.price - price) <= tol), None)
    return {
        "available": True,
        "nearest_support": sup.price if sup else None,
        "nearest_resistance": res.price if res else None,
        "on_level": on_level.price if on_level else None,
        "on_level_strength": on_level.strength if on_level else 0.0,
        "on_level_kind": on_level.kind if on_level else None,   # 'support'|'resistance' (pour le setup_side)
        "n_levels": len(levels),
        "note": (f"sur niveau {on_level.kind} (force {on_level.strength})" if on_level
                 else "entre deux niveaux"),
    }
