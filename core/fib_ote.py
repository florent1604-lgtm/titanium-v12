"""core/fib_ote.py — Retracement de Fibonacci + zone OTE (Optimal Trade Entry).

Brique de la méthode de Florent (critère n°4) : la « golden zone » Fibonacci reste
le point d'entrée optimal, MAIS doit être confirmée ; si la structure casse =
INVALIDE (comme un Order Block).

On détecte la dernière IMPULSION (jambe swing_low→swing_high ou l'inverse), on y
projette les retracements 0.382 / 0.5 / 0.618 / 0.705 / 0.786, et la zone OTE
= 0.618..0.786 (0.705 = cœur). Entrée dans l'OTE dans le sens de l'impulsion, sur
un PULLBACK ; invalidation si le prix dépasse l'origine de l'impulsion (>1.0).

API pure (numpy/pandas), sans look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

LEVELS = (0.382, 0.5, 0.618, 0.705, 0.786)
OTE_LOW, OTE_HIGH, GOLDEN = 0.618, 0.786, 0.705


@dataclass(frozen=True)
class FibZone:
    direction: int              # +1 impulsion haussière (setup LONG) / −1 (SHORT)
    swing_start: float          # origine de l'impulsion
    swing_end: float            # extrême de l'impulsion
    levels: Dict[float, float] = field(default_factory=dict)   # ratio -> prix
    ote_low: float = 0.0        # bord de la golden zone côté extrême
    ote_high: float = 0.0       # bord côté origine
    golden: float = 0.0         # 0.705
    invalidation: float = 0.0   # au-delà = structure cassée

    def in_ote(self, price: float) -> bool:
        lo, hi = sorted((self.ote_low, self.ote_high))
        return lo <= price <= hi

    def invalidated(self, price: float) -> bool:
        return price < self.invalidation if self.direction > 0 else price > self.invalidation


def _swings(highs, lows, k: int = 3):
    """Pivots fractals : indices des swing highs / lows (k barres de chaque côté)."""
    sh, sl = [], []
    n = len(highs)
    for i in range(k, n - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            sh.append(i)
        if lows[i] == min(lows[i - k:i + k + 1]):
            sl.append(i)
    return sh, sl


def compute_fib_ote(df: pd.DataFrame, *, k: int = 3) -> Optional[FibZone]:
    """Détecte la dernière impulsion et en projette la zone OTE."""
    if (not isinstance(k, (int, np.integer)) or k <= 0 or df is None
            or len(df) < 2 * k + 5 or not {"high", "low"}.issubset(df.columns)):
        return None
    highs = df["high"].to_numpy(float); lows = df["low"].to_numpy(float)
    if (not np.isfinite(highs).all() or not np.isfinite(lows).all()
            or np.any(highs < lows)):
        return None
    sh, sl = _swings(highs, lows, k)
    if not sh or not sl:
        return None
    last_h, last_l = sh[-1], sl[-1]

    if last_l < last_h:                     # dernière jambe = bas -> haut (haussière)
        direction = +1
        start, end = float(lows[last_l]), float(highs[last_h])
    else:                                    # haut -> bas (baissière)
        direction = -1
        start, end = float(highs[last_h]), float(lows[last_l])

    move = end - start
    if abs(move) < 1e-9:
        return None
    # prix à un ratio r : on retrace depuis l'extrême (end) vers l'origine (start)
    levels = {r: end - r * move for r in LEVELS}
    ote_low = end - OTE_LOW * move          # bord proche de l'extrême
    ote_high = end - OTE_HIGH * move        # bord proche de l'origine
    golden = end - GOLDEN * move
    invalidation = start                    # dépasser l'origine (>1.0) = invalide

    return FibZone(direction=direction, swing_start=start, swing_end=end,
                   levels={round(r, 3): round(p, 8) for r, p in levels.items()},
                   ote_low=ote_low, ote_high=ote_high, golden=golden,
                   invalidation=invalidation)


def entry_context(df: pd.DataFrame, price: float, *, k: int = 3) -> dict:
    """Le prix est-il dans la golden zone d'une impulsion valide ?"""
    if not np.isfinite(price) or price <= 0:
        return {"available": False}
    fz = compute_fib_ote(df, k=k)
    if fz is None:
        return {"available": False}
    return {
        "available": True, "direction": fz.direction,
        "ote_zone": (round(min(fz.ote_low, fz.ote_high), 8), round(max(fz.ote_low, fz.ote_high), 8)),
        "golden": round(fz.golden, 8), "invalidation": round(fz.invalidation, 8),
        "in_ote": fz.in_ote(price), "invalidated": fz.invalidated(price),
        "note": ("dans la golden zone (entrée optimale)" if fz.in_ote(price) and not fz.invalidated(price)
                 else "structure invalidée" if fz.invalidated(price)
                 else "hors zone OTE"),
    }
