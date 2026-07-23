"""core/volume_profile.py — Profil de volume : VPOC, Value Area, HVN/LVN.

Brique n°2 de la méthode de Florent (collab/FLORENT_ENTRY_METHOD.md) : les
« zones de juste prix ». Les volumes révèlent où les investisseurs estiment le
juste prix — le prix y REVIENT généralement avant de repartir en tendance.

Construit un histogramme volume-par-prix (chaque bougie répartit son volume sur
sa plage low..high), d'où :
  · VPOC  (Volume Point of Control) : le prix le plus échangé = le plus « accepté ».
  · Value Area (VAL..VAH) : la plage contenant ~70 % du volume autour du VPOC.
  · HVN (High Volume Nodes) : nœuds de forte acceptation → le prix y revient (entrée).
  · LVN (Low Volume Nodes) : zones de rejet → le prix les traverse vite (cible/stop).

API pure (numpy/pandas), sans look-ahead. Colonnes attendues : high, low, close, v.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VolumeProfile:
    vpoc: float                       # prix le plus échangé
    val: float                        # bas de la value area
    vah: float                        # haut de la value area
    hvn: List[float] = field(default_factory=list)   # nœuds de forte acceptation
    lvn: List[float] = field(default_factory=list)    # nœuds de rejet (vides)
    prices: List[float] = field(default_factory=list)  # centres des bins
    volumes: List[float] = field(default_factory=list) # volume par bin
    bin_size: float = 0.0

    def in_value_area(self, price: float) -> bool:
        return self.val <= price <= self.vah

    def nearest_hvn(self, price: float) -> Optional[float]:
        return min(self.hvn, key=lambda h: abs(h - price)) if self.hvn else None

    def dist_to_vpoc_pct(self, price: float) -> float:
        return (price - self.vpoc) / self.vpoc * 100.0 if self.vpoc else 0.0


def compute_profile(df: pd.DataFrame, *, bins: int = 50, window: Optional[int] = None,
                    value_area_pct: float = 0.70) -> Optional[VolumeProfile]:
    """Profil de volume sur df (ou ses `window` dernières bougies). Répartit le
    volume de chaque bougie uniformément sur sa plage low..high."""
    if (df is None or len(df) < 10 or not {"high", "low", "v"}.issubset(df.columns)
            or not isinstance(bins, (int, np.integer)) or bins <= 0
            or (window is not None and (not isinstance(window, (int, np.integer)) or window <= 0))
            or not np.isfinite(value_area_pct) or not 0.0 < value_area_pct <= 1.0):
        return None
    d = df.tail(window) if window else df
    highs = d["high"].to_numpy(float); lows = d["low"].to_numpy(float)
    vols = d["v"].to_numpy(float)
    if (not np.isfinite(highs).all() or not np.isfinite(lows).all()
            or not np.isfinite(vols).all() or np.any(highs < lows) or np.any(vols < 0)):
        return None
    lo, hi = float(lows.min()), float(highs.max())
    if hi - lo < 1e-12:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    bin_size = (hi - lo) / bins
    hist = np.zeros(bins)

    for h, l, v in zip(highs, lows, vols):
        if v <= 0 or h <= l:
            # bougie plate : tout le volume au niveau du prix
            idx = min(bins - 1, max(0, int((h - lo) / bin_size)))
            hist[idx] += max(v, 0.0)
            continue
        # fraction de la bougie [l,h] recouvrant chaque bin -> répartition du volume
        lo_b = max(0, int((l - lo) / bin_size))
        hi_b = min(bins - 1, int((h - lo) / bin_size))
        span = h - l
        for b in range(lo_b, hi_b + 1):
            overlap = min(h, edges[b + 1]) - max(l, edges[b])
            if overlap > 0:
                hist[b] += v * (overlap / span)

    total = hist.sum()
    if total <= 0:
        return None
    poc_idx = int(hist.argmax())
    vpoc = float(centers[poc_idx])

    # Value area : on étend depuis le POC en ajoutant le voisin le + volumineux.
    lo_i = hi_i = poc_idx
    acc = hist[poc_idx]
    target = total * value_area_pct
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left = hist[lo_i - 1] if lo_i > 0 else -1
        right = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1; acc += hist[hi_i]
        else:
            lo_i -= 1; acc += hist[lo_i]
    val, vah = float(centers[lo_i]), float(centers[hi_i])

    # HVN / LVN : maxima / minima locaux (lissage léger).
    sm = np.convolve(hist, np.array([0.25, 0.5, 0.25]), mode="same")
    hvn, lvn = [], []
    mean_v = sm.mean()
    for i in range(1, bins - 1):
        if sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > mean_v * 1.2:
            hvn.append(float(centers[i]))
        if sm[i] <= sm[i - 1] and sm[i] <= sm[i + 1] and sm[i] < mean_v * 0.5:
            lvn.append(float(centers[i]))

    return VolumeProfile(vpoc=vpoc, val=val, vah=vah, hvn=hvn, lvn=lvn,
                         prices=[float(c) for c in centers],
                         volumes=[float(v) for v in hist], bin_size=bin_size)


def entry_context(df: pd.DataFrame, price: float, *, window: int = 200) -> dict:
    """Lecture 'juste prix' pour une entrée : le prix est-il sur/proche d'un nœud
    de valeur (le marché y revient) ou dans le vide (mouvement rapide) ?"""
    if not np.isfinite(price) or price <= 0:
        return {"available": False}
    prof = compute_profile(df, window=window)
    if prof is None:
        return {"available": False}
    hvn = prof.nearest_hvn(price)
    near_hvn = hvn is not None and abs(price - hvn) <= 2 * prof.bin_size
    return {
        "available": True, "vpoc": prof.vpoc, "val": prof.val, "vah": prof.vah,
        "in_value_area": prof.in_value_area(price),
        "nearest_hvn": hvn, "on_fair_price_zone": near_hvn,
        "dist_to_vpoc_pct": round(prof.dist_to_vpoc_pct(price), 3),
        "note": "sur zone de juste prix (retour probable)" if near_hvn
                else ("dans la value area" if prof.in_value_area(price) else "hors value area (déséquilibre)"),
    }
