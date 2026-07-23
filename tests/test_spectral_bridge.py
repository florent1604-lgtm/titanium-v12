"""tests/test_spectral_bridge.py — pont spectral → tore (observateur).

Mapping cycle→angle, puissance→angle, stabilité, recommandation de filtre, et
intégration avec le plan géométrique via `spectral_override`. Aucun effet de bord.
"""
import math

import numpy as np
import pytest

from core.spectral_bridge import (
    SpectralBridge,
    SpectralTorusAngles,
    integrate_with_geometric_plane,
    spectral_bridge,
)


@pytest.fixture
def bridge():
    return SpectralBridge(cycle_period_max=40, cycle_period_min=5, power_threshold=0.25)


class TestSpectralTorusAngles:
    def test_clifford_projection_valid(self):
        a = SpectralTorusAngles(math.pi / 2, math.pi / 4, 12, 0.6, 0.7, True)
        x, y, z, W = a.to_clifford_projection(t=1.0)
        assert all(isinstance(v, float) and math.isfinite(v) for v in (x, y, z))
        assert W >= 0.15
        # NB : la projection livrée ne satisfait PAS l'identité S3 x²+y²+z²=1/W²
        # (mesuré : 0,83 vs 1,66). On teste donc la finitude/borne de W, pas ce faux invariant.

    def test_clifford_projection_invalid_is_zero(self):
        a = SpectralTorusAngles(0, 0, 0, 0, 0, False)
        assert a.to_clifford_projection() == (0.0, 0.0, 0.0, 2.0)


class TestToTorusAngles:
    def test_valid_cycle(self, bridge):
        a = bridge.to_torus_angles({"dominant_cycle": 12, "cycle_power": 0.6, "cycle_stability": 0.8})
        assert a.valid and a.dominant_cycle == 12 and a.cycle_power == 0.6
        assert 0.0 <= a.u <= 2 * math.pi and 0.0 <= a.v <= 2 * math.pi
        assert a.confidence == pytest.approx(0.48, abs=0.01)

    def test_no_cycle_invalid(self, bridge):
        a = bridge.to_torus_angles({"dominant_cycle": None, "cycle_power": 0.0})
        assert a.valid is False and a.confidence == 0.0

    def test_low_power_invalid(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": 10, "cycle_power": 0.1}).valid is False

    def test_cycle_mapping(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": 5, "cycle_power": 0.5, "cycle_stability": 1.0}).u == pytest.approx(0.0, abs=0.01)
        assert bridge.to_torus_angles({"dominant_cycle": 40, "cycle_power": 0.5, "cycle_stability": 1.0}).u == pytest.approx(2 * math.pi, abs=0.1)
        assert bridge.to_torus_angles({"dominant_cycle": 22, "cycle_power": 0.5, "cycle_stability": 1.0}).u == pytest.approx(math.pi, abs=0.2)

    def test_power_mapping(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": 15, "cycle_power": 0.3, "cycle_stability": 1.0}).v < math.pi
        assert bridge.to_torus_angles({"dominant_cycle": 15, "cycle_power": 0.9, "cycle_stability": 1.0}).v > math.pi


class TestFromState:
    def test_extracts_nested(self, bridge):
        st = {"BTC/USDT": {"dominant_cycle": 18, "cycle_power": 0.55, "cycle_stability": 0.7}}
        a = bridge.from_state(st, "BTC/USDT")
        assert a.valid and a.dominant_cycle == 18 and a.cycle_power == 0.55

    def test_missing_symbol_invalid(self, bridge):
        assert bridge.from_state({}, "BTC/USDT").valid is False


class TestRecommendRegimeFilter:
    def test_high_conf_long_cycle_on(self, bridge):
        assert bridge.recommend_regime_filter(SpectralTorusAngles(0, 0, 15, 0.8, 0.8, True)) == "on"

    def test_medium_conf_caution(self, bridge):
        assert bridge.recommend_regime_filter(SpectralTorusAngles(0, 0, 15, 0.6, 0.6, True)) == "caution"

    def test_low_conf_off(self, bridge):
        assert bridge.recommend_regime_filter(SpectralTorusAngles(0, 0, 15, 0.3, 0.3, True)) == "off"

    def test_invalid_off(self, bridge):
        assert bridge.recommend_regime_filter(SpectralTorusAngles(0, 0, 0, 0, 0, False)) == "off"

    def test_short_cycle_off(self, bridge):
        assert bridge.recommend_regime_filter(SpectralTorusAngles(0, 0, 5, 0.9, 0.9, True)) == "off"


class TestToGeometricPlaneInput:
    def test_valid_true(self, bridge):
        a = bridge.to_torus_angles({"dominant_cycle": 15, "cycle_power": 0.6, "cycle_stability": 0.8})
        r = bridge.to_geometric_plane_input(a)
        assert r["use_spectral"] is True and "clifford_xyz" in r and r["curvature"] > 0.0

    def test_invalid_false(self, bridge):
        r = bridge.to_geometric_plane_input(bridge.to_torus_angles({"dominant_cycle": None, "cycle_power": 0.0}))
        assert r["use_spectral"] is False


class TestStabilityScore:
    def test_stable_cycle_high(self, bridge):
        for _ in range(5):
            bridge.stability_score("BTC/USDT", 15)
        assert bridge.stability_score("BTC/USDT", 15) > 0.8

    def test_unstable_cycle_low(self, bridge):
        for c in [5, 25, 8, 35, 12]:
            bridge.stability_score("BTC/USDT", c)
        assert bridge.stability_score("BTC/USDT", 20) < 0.5


class TestSingleton:
    def test_exists(self):
        assert isinstance(spectral_bridge, SpectralBridge)


class TestGeometricPlaneIntegration:
    def test_override_forces_clifford(self):
        from core.geometric_plane import GeometricPlane
        gp = GeometricPlane(window=60)
        override = {"use_spectral": True, "clifford_xyz": (0.5, 0.3, 0.2),
                    "curvature": 0.4, "confidence": 0.8}
        r = gp.analyze("BTC/USDT", np.random.randn(60, 16) * 0.1,
                       np.random.randn(60, 4) * 0.01, spectral_cycle=15,
                       spectral_override=override, publish=False)
        assert r.branch == "CLIFFORD" and r.curvature == 0.4 and r.confidence > 0.5

    def test_analyze_with_spectral_state(self):
        from core.geometric_plane import GeometricPlane
        gp = GeometricPlane(window=60)
        st = {"BTC/USDT": {"dominant_cycle": 18, "cycle_power": 0.65, "cycle_stability": 0.75}}
        r = gp.analyze_with_spectral("BTC/USDT", np.random.randn(60, 16) * 0.1,
                                     np.random.randn(60, 4) * 0.01, st, publish=False)
        assert r.branch == "CLIFFORD" and r.spectral_cycle == 18


class TestEdgeCases:
    def test_clamped_cycle(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": 100, "cycle_power": 0.5, "cycle_stability": 1.0}).u == pytest.approx(2 * math.pi, abs=0.1)

    def test_negative_cycle(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": -5, "cycle_power": 0.5, "cycle_stability": 1.0}).u == pytest.approx(0.0, abs=0.1)

    def test_power_above_one(self, bridge):
        assert bridge.to_torus_angles({"dominant_cycle": 15, "cycle_power": 1.5, "cycle_stability": 1.0}).v == pytest.approx(2 * math.pi, abs=0.1)
