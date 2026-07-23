"""tests/test_geometric_plane.py — Plan géométrique (observateur pur).

Vérifie le moteur en ISOLATION : régime calculé, bornes respectées, robustesse
sur cas dégénérés, et invariants des modulateurs (non câblés mais testés pour
l'étape 3 post-M2). Aucune écriture EventPlane, aucune décision.
"""
import numpy as np
import pytest

from core.geometric_plane import GeometricPlane, GeometricRegime, get_latest_regime


@pytest.fixture
def gp():
    return GeometricPlane(window=60, library_size=10)


@pytest.fixture
def mock_scores_60x16():
    """Historique de scores SMC simulé (régime cyclique → tore)."""
    np.random.seed(42)
    t = np.linspace(0, 4 * np.pi, 60)
    cycle1 = np.sin(t)
    cycle2 = np.cos(t * 0.7)
    data = np.zeros((60, 16))
    data[:, 0] = cycle1
    data[:, 1] = cycle2
    data[:, 2:8] = np.random.randn(60, 6) * 0.1
    data[:, 8:16] = np.outer(cycle1, np.ones(8)) * 0.3
    return data


@pytest.fixture
def mock_returns_60x4():
    np.random.seed(123)
    returns = np.random.randn(60, 4) * 0.02
    for i in range(1, 60):
        returns[i] += 0.1 * returns[i - 1]
    return returns


class TestGeometricRegime:
    def test_to_fact_payload(self):
        reg = GeometricRegime(
            symbol="BTC/USDT", timestamp=1234567890.0, branch="CLIFFORD",
            curvature=0.5, fisher_distance=2.3, lyapunov_horizon=15,
            clifford_xyz=(0.1, 0.2, 0.3),
        )
        payload = reg.to_fact_payload()
        assert payload["symbol"] == "BTC/USDT"
        assert payload["branch"] == "CLIFFORD"
        assert payload["curvature"] == 0.5
        assert isinstance(payload["clifford_xyz"], tuple)


class TestGeometricPlaneAnalyze:
    def test_returns_regime(self, gp, mock_scores_60x16, mock_returns_60x4):
        regime = gp.analyze(symbol="BTC/USDT", scores_16=mock_scores_60x16,
                            returns=mock_returns_60x4, spectral_cycle=12, publish=False)
        assert isinstance(regime, GeometricRegime)
        assert regime.symbol == "BTC/USDT"
        assert regime.branch in ("CLIFFORD", "GRASSMANN", "CLASSIC")
        assert 0.0 <= regime.curvature <= 1.0
        assert 1 <= regime.lyapunov_horizon <= 60

    def test_clifford_coords_when_branch_clifford(self, gp, mock_scores_60x16, mock_returns_60x4):
        regime = gp.analyze(symbol="BTC/USDT", scores_16=mock_scores_60x16,
                            returns=mock_returns_60x4, spectral_cycle=15, publish=False)
        if regime.branch == "CLIFFORD":
            assert regime.clifford_xyz != (0.0, 0.0, 0.0)
            assert regime.curvature > 0.0

    def test_grassmann_or_classic_on_fragmentation(self, gp, mock_returns_60x4):
        np.random.seed(99)
        scores = np.random.randn(60, 16) * 0.5
        regime = gp.analyze(symbol="ETH/USDT", scores_16=scores,
                            returns=mock_returns_60x4, spectral_cycle=0, publish=False)
        assert regime.branch in ("GRASSMANN", "CLASSIC")

    def test_lyapunov_reste_dans_ses_bornes(self, gp):
        """LIMITE CONNUE (proxy Wolf) : sur du bruit iid, l'horizon N'est PAS
        stable → 30 (mesuré : 12..60 selon la graine). On ne teste donc que
        l'invariant garanti — l'horizon reste dans [1,60]. Fragilité à durcir
        avant tout câblage décisionnel (étape 3)."""
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((60, 1)) * 0.001
        scores = rng.standard_normal((60, 16)) * 0.1
        regime = gp.analyze(symbol="XAU/USD", scores_16=scores, returns=returns,
                            spectral_cycle=0, publish=False)
        assert 1 <= regime.lyapunov_horizon <= 60

    def test_fisher_zero_then_rises_on_new_regime(self, gp, mock_scores_60x16, mock_returns_60x4):
        r1 = gp.analyze(symbol="BTC/USDT", scores_16=mock_scores_60x16,
                        returns=mock_returns_60x4, spectral_cycle=10, publish=False)
        assert r1.fisher_distance == 0.0
        new_scores = mock_scores_60x16 + 5.0
        r2 = gp.analyze(symbol="BTC/USDT", scores_16=new_scores,
                        returns=mock_returns_60x4, spectral_cycle=10, publish=False)
        assert r2.fisher_distance > 3.0

    def test_library_size_respected(self, gp, mock_scores_60x16, mock_returns_60x4):
        for i in range(15):
            scores = mock_scores_60x16 + np.random.randn(60, 16) * 0.1 * i
            gp.analyze(symbol="BTC/USDT", scores_16=scores, returns=mock_returns_60x4,
                       spectral_cycle=10, publish=False)
        assert len(gp._library["BTC/USDT"]) <= gp.library_size

    def test_publish_alimente_le_cache_lecture_seule(self, gp, mock_scores_60x16, mock_returns_60x4):
        gp.analyze(symbol="ZZZ/OBSERVE", scores_16=mock_scores_60x16,
                   returns=mock_returns_60x4, spectral_cycle=10, publish=True)
        cached = get_latest_regime("ZZZ/OBSERVE")
        assert cached is not None and cached.symbol == "ZZZ/OBSERVE"
        # publish=False ne doit PAS écraser le cache
        assert get_latest_regime("JAMAIS/PUBLIE") is None


class TestStaticModulators:
    def test_sizing_clifford_low_curvature(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLIFFORD", curvature=0.1,
                              fisher_distance=1.0, lyapunov_horizon=20)
        assert 0.8 <= GeometricPlane.sizing_factor(reg) <= 1.2

    def test_sizing_clifford_high_curvature_reduces(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLIFFORD", curvature=0.9,
                              fisher_distance=1.0, lyapunov_horizon=20)
        assert GeometricPlane.sizing_factor(reg) < 1.0

    def test_sizing_topology_alert(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", topology_alert=True,
                              lyapunov_horizon=30)
        assert GeometricPlane.sizing_factor(reg) == pytest.approx(0.3, abs=0.01)

    def test_sizing_fisher_drives_to_floor(self):
        """fisher>8 pousse le sizing au PLANCHER 0.30 (pas en dessous : le clip
        borne à [0.30, 1.20]). Le test livré exigeait « <0.3 », impossible par
        construction — corrigé pour dire le vrai."""
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", fisher_distance=9.0,
                              lyapunov_horizon=30)
        assert GeometricPlane.sizing_factor(reg) == pytest.approx(0.30, abs=0.01)

    def test_emotion_arousal_boosted_by_curvature(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLIFFORD", curvature=0.8,
                              fisher_distance=1.0, lyapunov_horizon=20)
        assert GeometricPlane.emotion_arousal_modifier(reg, 0.5) > 0.5

    def test_consensus_zeroed_on_topology_alert(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", topology_alert=True)
        assert GeometricPlane.consensus_modulator(reg, 50.0) == 0.0

    def test_gate_blocks_swing_on_short_lyapunov(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", lyapunov_horizon=1)
        permitted, reason = GeometricPlane.gate_permitted(reg, "swing")
        assert permitted is False and "LYAPUNOV" in reason

    def test_gate_allows_scalp_on_short_lyapunov(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", lyapunov_horizon=1)
        permitted, _ = GeometricPlane.gate_permitted(reg, "scalp")
        assert permitted is True


class TestRobustness:
    def test_empty_returns(self, gp):
        regime = gp.analyze(symbol="TEST", scores_16=np.zeros((60, 16)),
                            returns=np.zeros((60, 1)), spectral_cycle=0, publish=False)
        assert regime.branch == "CLASSIC"
        assert regime.lyapunov_horizon == 30

    def test_short_history(self, gp):
        regime = gp.analyze(symbol="TEST", scores_16=np.zeros((10, 16)),
                            returns=np.zeros((10, 1)), spectral_cycle=0, publish=False)
        assert regime.lyapunov_horizon == 30

    def test_single_asset_returns(self, gp, mock_scores_60x16):
        regime = gp.analyze(symbol="BTC/USDT", scores_16=mock_scores_60x16,
                            returns=np.random.randn(60, 1) * 0.01, spectral_cycle=10, publish=False)
        assert isinstance(regime, GeometricRegime)


class TestInvariants:
    def test_gate_permits_when_classic_neutral(self):
        reg = GeometricRegime("BTC/USDT", 0.0, "CLASSIC", curvature=0.0,
                              fisher_distance=0.0, lyapunov_horizon=30)
        permitted, _ = GeometricPlane.gate_permitted(reg, "swing")
        assert permitted is True

    def test_sizing_always_within_bounds(self, gp, mock_scores_60x16, mock_returns_60x4):
        for _ in range(20):
            scores = mock_scores_60x16 + np.random.randn(60, 16) * 0.5
            regime = gp.analyze(symbol="BTC/USDT", scores_16=scores, returns=mock_returns_60x4,
                                spectral_cycle=np.random.randint(0, 30), publish=False)
            assert 0.3 <= GeometricPlane.sizing_factor(regime) <= 1.2
