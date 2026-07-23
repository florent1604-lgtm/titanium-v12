"""core/spectral_bridge.py — Pont spectral → tore de Clifford (OBSERVATEUR).

Relie le module spectral existant (Ehlers CAUSAL, `indicators/spectral.py::analyze`)
au plan géométrique : le cycle dominant devient l'angle u du tore, la puissance du
cycle l'angle v. Pur calcul O(1) sur des sorties déjà produites — aucun effet de bord.

⚠️ CAUSALITÉ. On consomme UNIQUEMENT `indicators/spectral.py::analyze()` (100 %
causal). L'autre API du module, `compute_spectral_features`, utilise du look-ahead
(filtfilt/hilbert) → backtest seulement, JAMAIS ce pont.

⚠️ PÉRIMÈTRE. Ce pont alimente l'OBSERVATEUR géométrique. Il ne touche NI le scorer
live NI `SPECTRAL_REGIME_FILTER` (qui reste OFF jusqu'à validation walk-forward,
consigne CLAUDE.md). L'activation du filtre et le câblage signal_engine sont différés.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np


@dataclass(frozen=True, slots=True)
class SpectralTorusAngles:
    """Angles du tore dérivés du spectral."""
    u: float
    v: float
    dominant_cycle: int
    cycle_power: float
    confidence: float
    valid: bool

    def to_clifford_projection(self, t: float = 1.0) -> Tuple[float, float, float, float]:
        """Projection stéréographique du tore → (x, y, z, W)."""
        if not self.valid:
            return (0.0, 0.0, 0.0, 2.0)
        W = 2.0 - (math.sin(self.u) * math.sin(t) + math.sin(self.v) * math.cos(t))
        W = max(W, 0.15)
        x = math.cos(self.u) / W
        y = (math.sin(self.u) * math.cos(t) - math.sin(self.v) * math.sin(t)) / W
        z = math.cos(self.v) / W
        return (x, y, z, W)


class SpectralBridge:
    """Convertit les sorties du spectral Ehlers en angles du tore. PUR."""

    def __init__(self, cycle_period_max: int = 40, cycle_period_min: int = 5,
                 power_threshold: float = 0.25):
        self.cycle_max = cycle_period_max
        self.cycle_min = cycle_period_min
        self.power_threshold = power_threshold
        self._cycle_history: Dict[str, list] = {}
        self._history_len = 10

    def to_torus_angles(self, spectral_result: Dict[str, Any]) -> SpectralTorusAngles:
        """`{dominant_cycle, cycle_power, cycle_stability?}` → angles du tore."""
        cycle = spectral_result.get("dominant_cycle")
        power = float(spectral_result.get("cycle_power", 0.0) or 0.0)
        stability = float(spectral_result.get("cycle_stability", 0.5) or 0.5)

        if cycle is None or power < self.power_threshold:
            return SpectralTorusAngles(0.0, 0.0, 0, power, 0.0, False)

        cycle_clamped = max(self.cycle_min, min(int(cycle), self.cycle_max))
        cycle_norm = (cycle_clamped - self.cycle_min) / (self.cycle_max - self.cycle_min)
        u = 2.0 * math.pi * cycle_norm
        v = 2.0 * math.pi * min(power, 1.0)
        confidence = power * stability
        return SpectralTorusAngles(u, v, int(cycle), power, confidence, True)

    def from_state(self, spectral_state: Dict[str, Any], symbol: str) -> SpectralTorusAngles:
        """Extrait les angles depuis `spectral_state = {sym: {dominant_cycle, cycle_power}}`."""
        return self.to_torus_angles(spectral_state.get(symbol, {}) or {})

    def stability_score(self, symbol: str, current_cycle: int) -> float:
        """Stabilité du cycle ∈ [0,1] d'après l'historique récent (faible variance = stable).

        Correction Claude (23/07) : l'historique est alimenté À CHAQUE appel (la version
        livrée sortait avant d'accumuler → toujours 0.5)."""
        hist = self._cycle_history.setdefault(symbol, [])
        hist.append(int(current_cycle))
        if len(hist) > self._history_len:
            hist.pop(0)
        if len(hist) < 3:
            return 0.5
        variance = float(np.var(hist[-5:]))
        return float(math.exp(-variance / 10.0))

    def recommend_regime_filter(self, angles: SpectralTorusAngles) -> str:
        """Recommandation (INDICATIVE) pour SPECTRAL_REGIME_FILTER : "on"|"caution"|"off".

        Correction Claude (23/07) : un court cycle (≤ 8 barres) est trop bruité pour
        qu'on s'y fie → "off" quelle que soit la confiance (la version livrée tombait à
        tort en "caution" via la branche confiance)."""
        if not angles.valid:
            return "off"
        if angles.dominant_cycle <= 8:
            return "off"
        if angles.confidence > 0.7:
            return "on"
        if angles.confidence > 0.5:
            return "caution"
        return "off"

    def to_geometric_plane_input(self, angles: SpectralTorusAngles) -> Dict[str, Any]:
        """Formate les angles pour `GeometricPlane.analyze(spectral_override=...)`."""
        if not angles.valid:
            return {"use_spectral": False}
        x, y, z, W = angles.to_clifford_projection(t=1.0)
        return {
            "use_spectral": True,
            "spectral_angles": angles,
            "clifford_xyz": (x, y, z),
            "curvature": min(1.0, abs(1.0 / W)),
            "confidence": angles.confidence,
        }


spectral_bridge = SpectralBridge()


def integrate_with_geometric_plane(geo_plane, spectral_state: Dict[str, Any],
                                   symbol: str) -> Optional[Dict[str, Any]]:
    """Helper : `spectral_state` → entrée `spectral_override` pour le plan géométrique."""
    angles = spectral_bridge.from_state(spectral_state, symbol)
    return spectral_bridge.to_geometric_plane_input(angles)
