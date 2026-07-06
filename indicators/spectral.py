"""indicators/spectral.py — Analyse spectrale des cycles de prix (Phase 1).

Clean-room, inspiré des travaux de John Ehlers (roofing filter, autocorrelation
periodogram). Tout est CAUSAL : chaque valeur n'utilise que le passé, donc le
module est utilisable en live sans lookahead — garde-fou n°1 de la roadmap.

North star 2D → 3D → 4D :
  - 3D : cycle dominant + puissance cyclique (filtre de régime)  ← ce module
  - 4D : phase instantanée (timing)                              ← ce module

Sortie unique : analyze(close) → dict
  dominant_cycle  : période dominante en barres (0 si aucun cycle net)
  cycle_power     : part de la puissance du cycle dominant [0..1]
  has_cycle       : cycle_power >= SPECTRAL_POWER_THRESHOLD
  phase_deg       : phase instantanée du cycle dominant [0..360)
  phase_zone      : "creux" | "montée" | "sommet" | "descente"
                    (à CALIBRER par paire avant tout usage signal — roadmap)
"""
from __future__ import annotations
import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

from utils.config import (
    SPECTRAL_PMIN, SPECTRAL_PMAX, SPECTRAL_POWER_THRESHOLD,
)


def roofing_filter(close: np.ndarray, hp_period: int = 48, ss_period: int = 10) -> np.ndarray:
    """Passe-bande causal : highpass 2 pôles + SuperSmoother d'Ehlers.

    Isole les composantes cycliques entre ss_period et hp_period barres,
    supprime la tendance (basse fréquence) et le bruit (haute fréquence).
    IIR → strictement causal, utilisable bar-par-bar en live.
    """
    n = len(close)
    if n < 5:
        return np.zeros(n)

    # Highpass 2 pôles
    a = math.sqrt(0.5) * 2 * math.pi / hp_period
    alpha1 = (math.cos(a) + math.sin(a) - 1) / math.cos(a)
    hp = np.zeros(n)
    c1 = (1 - alpha1 / 2) ** 2
    for i in range(2, n):
        hp[i] = (c1 * (close[i] - 2 * close[i - 1] + close[i - 2])
                 + 2 * (1 - alpha1) * hp[i - 1]
                 - (1 - alpha1) ** 2 * hp[i - 2])

    # SuperSmoother 2 pôles
    a2 = math.sqrt(2.0) * math.pi / ss_period
    b1 = 2 * math.exp(-a2 / math.sqrt(2.0)) * math.cos(a2)
    c3 = -math.exp(-2 * a2 / math.sqrt(2.0))
    c2 = b1
    c1s = 1 - c2 - c3
    out = np.zeros(n)
    for i in range(2, n):
        out[i] = c1s * (hp[i] + hp[i - 1]) / 2 + c2 * out[i - 1] + c3 * out[i - 2]
    return out


def _dft_power(sig: np.ndarray, period: int) -> float:
    """Puissance du signal à une période donnée (DFT à fréquence unique)."""
    n = len(sig)
    w = 2 * math.pi / period
    idx = np.arange(n)
    re = float(np.dot(sig, np.cos(w * idx)))
    im = float(np.dot(sig, np.sin(w * idx)))
    return re * re + im * im


def analyze(close_series: pd.Series) -> Optional[Dict[str, object]]:
    """Analyse spectrale complète sur les dernières barres.

    Fenêtre = 3×pmax barres (assez pour résoudre le cycle le plus lent
    sans traîner des régimes morts). Retourne None si données insuffisantes.
    """
    if close_series is None or len(close_series) < SPECTRAL_PMAX * 2:
        return None

    window = int(SPECTRAL_PMAX * 3)
    close = close_series.values.astype(float)[-window:]
    filt = roofing_filter(close, hp_period=SPECTRAL_PMAX, ss_period=max(SPECTRAL_PMIN, 8))

    # Warm-up du filtre IIR : on jette le premier tiers
    sig = filt[len(filt) // 3:]
    if len(sig) < SPECTRAL_PMAX:
        return None
    sig = sig - sig.mean()
    if float(np.abs(sig).max()) < 1e-12:
        return None

    # Périodogramme : puissance par période candidate
    periods = range(SPECTRAL_PMIN, SPECTRAL_PMAX + 1)
    powers = {p: _dft_power(sig, p) for p in periods}
    total = sum(powers.values()) or 1e-12
    dom_p, dom_pow = max(powers.items(), key=lambda kv: kv[1])
    # Puissance relative : part du cycle dominant et de ses voisins immédiats
    neighborhood = sum(powers.get(p, 0.0) for p in (dom_p - 1, dom_p, dom_p + 1))
    cycle_power = round(neighborhood / total, 3)
    has_cycle = cycle_power >= SPECTRAL_POWER_THRESHOLD

    # Phase instantanée : corrélation des dernières `dom_p` barres avec
    # sin/cos à la période dominante (causal — fenêtre passée uniquement)
    tail = sig[-dom_p:]
    idx = np.arange(dom_p)
    w = 2 * math.pi / dom_p
    re = float(np.dot(tail, np.cos(w * idx)))
    im = float(np.dot(tail, np.sin(w * idx)))
    phase = (math.degrees(math.atan2(im, re)) + 360.0) % 360.0

    if phase < 90:      zone = "creux"      # bas de cycle — zone d'achat potentielle
    elif phase < 180:   zone = "montée"
    elif phase < 270:   zone = "sommet"     # haut de cycle — zone de vente potentielle
    else:               zone = "descente"

    return {
        "dominant_cycle": int(dom_p) if has_cycle else 0,
        "cycle_power":    cycle_power,
        "has_cycle":      has_cycle,
        "phase_deg":      round(phase, 1),
        "phase_zone":     zone if has_cycle else "aucun",
    }
