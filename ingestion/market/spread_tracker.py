"""data/spread_tracker.py — Spread temps réel par symbole.

Remplace le PAPER_SPREAD_BPS statique par une mesure réelle du spread
depuis le carnet d'ordres L2 :
  - Spread instantané : (best_ask - best_bid) / mid × 10000
  - Spread moyen glissant (EMA)
  - Spread effectif ajusté pour la taille de l'ordre (market impact)
"""
from __future__ import annotations
import time
from collections import deque
from typing import Dict, Optional
import utils.config as _cfg
from utils.config import (
    SYMBOLS, SPREAD_EMA_WINDOW,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class SpreadTracker:
    """Tracker de spread temps réel alimenté par le WebSocket depth."""

    def __init__(self) -> None:
        self._spreads: Dict[str, deque] = {
            s: deque(maxlen=300) for s in SYMBOLS  # ~30s à 100ms
        }
        self._ema: Dict[str, float] = {s: 0.0 for s in SYMBOLS}
        self._alpha = 2.0 / (SPREAD_EMA_WINDOW + 1)

    def update(self, sym: str, spread_bps: float) -> None:
        """Appelé à chaque mise à jour du carnet d'ordres."""
        if spread_bps <= 0:
            return
        self._spreads[sym].append((time.time(), spread_bps))
        # EMA update
        if self._ema[sym] == 0:
            self._ema[sym] = spread_bps
        else:
            self._ema[sym] = self._alpha * spread_bps + (1 - self._alpha) * self._ema[sym]

    def get_spread_bps(self, sym: str) -> float:
        """Retourne le spread EMA glissant, ou le fallback statique."""
        if not _cfg.SPREAD_USE_REALTIME:
            return _cfg.PAPER_SPREAD_BPS
        ema = self._ema.get(sym, 0.0)
        return ema if ema > 0 else _cfg.PAPER_SPREAD_BPS

    def get_instantaneous(self, sym: str) -> float:
        """Retourne le dernier spread observé."""
        buf = self._spreads.get(sym)
        if buf:
            return buf[-1][1]
        return _cfg.PAPER_SPREAD_BPS

    def get_effective_spread(self, sym: str, size_usdt: float = 0) -> float:
        """Spread effectif ajusté pour la taille de l'ordre.

        Pour les petits ordres (< 500$), le spread est le bid-ask standard.
        Pour les gros ordres, on estime le market impact en traversant le carnet.
        """
        base_spread = self.get_spread_bps(sym)

        if size_usdt <= 500:
            return base_spread

        # Estimation simplifiée du market impact
        # Impact = base_spread × (1 + log2(size / 500))
        import math
        impact_mult = 1.0 + math.log2(max(1, size_usdt / 500))
        return base_spread * min(impact_mult, 5.0)  # cap à 5× le spread

    def get_stats(self, sym: str) -> dict:
        """Statistiques de spread pour le dashboard."""
        buf = self._spreads.get(sym, deque())
        if not buf:
            return {"spread_bps": _cfg.PAPER_SPREAD_BPS, "samples": 0, "source": "static"}
        spreads = [s[1] for s in buf]
        return {
            "spread_bps": round(self._ema.get(sym, 0), 2),
            "spread_min": round(min(spreads), 2),
            "spread_max": round(max(spreads), 2),
            "spread_instant": round(spreads[-1], 2),
            "samples": len(spreads),
            "source": "realtime",
        }


# Singleton
spread_tracker = SpreadTracker()
