"""tests/test_brain_gate_geometric.py — le plan géométrique CÂBLÉ dans la porte.

Verrouille le comportement du câblage décisionnel (démo, 23/07) : le régime FILTRE
et DIMENSIONNE, et son absence laisse la porte STRICTEMENT inchangée (fail-safe).
"""
import time

import pytest

from core import geometric_plane as gp
from core.brain_gate import AUTO, gate_entry

_CONS = {"status": "CONFIRMED", "side": "long", "conflict": False,
         "consensus_score": 60, "directional_coverage": 0.8}
_CF = lambda s: _CONS          # noqa: E731
_MF = lambda s: AUTO           # noqa: E731


@pytest.fixture(autouse=True)
def _clean():
    for k in ("GEO_TEST", "GEO_VIDE"):
        gp._LATEST.pop(k, None)
    yield
    for k in ("GEO_TEST", "GEO_VIDE"):
        gp._LATEST.pop(k, None)


def test_regime_sain_autorise_et_size():
    gp._LATEST["GEO_TEST"] = gp.GeometricRegime("GEO_TEST", time.time(), "CLIFFORD",
                                                curvature=0.1, fisher_distance=1.0, lyapunov_horizon=20)
    g = gate_entry("GEO_TEST", 1, consensus_fn=_CF, master_fn=_MF)
    assert g.allow is True
    assert "GEOM_CLIFFORD" in g.reason_codes
    assert 0.0 < g.conviction <= 1.0


def test_rupture_topologique_bloque():
    gp._LATEST["GEO_TEST"] = gp.GeometricRegime("GEO_TEST", time.time(), "CLASSIC",
                                                topology_alert=True, lyapunov_horizon=30)
    g = gate_entry("GEO_TEST", 1, consensus_fn=_CF, master_fn=_MF)
    assert g.allow is False and "GEOM_TOPOLOGY_ALERT" in g.reason_codes


def test_fisher_regime_inconnu_bloque_le_swing():
    gp._LATEST["GEO_TEST"] = gp.GeometricRegime("GEO_TEST", time.time(), "CLASSIC",
                                                fisher_distance=9.0, lyapunov_horizon=30)
    g = gate_entry("GEO_TEST", 1, consensus_fn=_CF, master_fn=_MF)
    assert g.allow is False and "GEOM_FISHER_UNKNOWN_REGIME" in g.reason_codes


def test_sizing_reduit_la_conviction():
    """Une courbure/Fisher défavorable doit RÉDUIRE la taille par rapport au régime neutre."""
    gp._LATEST["GEO_TEST"] = gp.GeometricRegime("GEO_TEST", time.time(), "CLIFFORD",
                                                curvature=0.1, fisher_distance=1.0, lyapunov_horizon=20)
    haut = gate_entry("GEO_TEST", 1, consensus_fn=_CF, master_fn=_MF).conviction
    gp._LATEST["GEO_TEST"] = gp.GeometricRegime("GEO_TEST", time.time(), "GRASSMANN",
                                                grassmann_rotation=25.0, fisher_distance=6.0, lyapunov_horizon=4)
    bas = gate_entry("GEO_TEST", 1, consensus_fn=_CF, master_fn=_MF).conviction
    assert bas < haut


def test_absence_de_regime_est_fail_safe():
    """Sans régime en cache : porte STRICTEMENT identique à avant le câblage."""
    g = gate_entry("GEO_VIDE", 1, consensus_fn=_CF, master_fn=_MF)
    assert g.allow is True
    assert "BRAIN_ALLOW" in g.reason_codes
    assert not any(str(r).startswith("GEOM_") for r in g.reason_codes)
