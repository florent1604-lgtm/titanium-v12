"""tests/test_modulator.py — Tests unitaires du SignalModulator.

Les seuils de production sont :
  FUNDAMENTALS_RISK_REDUCE = 50.0
  FUNDAMENTALS_RISK_BLOCK  = 90.0

Les tests utilisent ces valeurs réelles pour valider la logique.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fundamentals.signal_modulator import (
    modulate, force_enable, force_disable, is_active, get_modulation_stats,
)

_BASE_SIGNAL = {
    "symbol": "BTC/USDT",
    "score":  8,
    "side":   "ACHAT",
    "active": True,
    "price":  95000.0,
    "confs":  ["EMA200-H4 haussier", "BOS H2/H1"],
}


def test_pass_through_low_risk():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=15.0)
    assert result is not None
    assert result["score"] == 8, f"Score ne devrait pas changer: {result['score']}"
    assert result["risk_factor"] == 1.0


def test_reduce_medium_risk():
    """risk_score > RISK_REDUCE (50) → score réduit avec factor < 1.0."""
    force_enable()
    # risk_score=60 est entre REDUCE(50) et BLOCK(90)
    result = modulate(dict(_BASE_SIGNAL), risk_score=60.0)
    assert result is not None
    assert result["score"] < 8, f"Score devrait être réduit: {result['score']}"
    assert 0.5 <= result["risk_factor"] < 1.0
    assert result.get("score_original") == 8


def test_block_high_risk():
    """risk_score >= RISK_BLOCK (90) → signal annulé."""
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=90.0)
    assert result is None, f"Signal devrait être annulé à risk=90: {result}"


def test_block_extreme_risk():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=95.0)
    assert result is None


def test_passthrough_when_disabled():
    force_disable("test")
    result = modulate(dict(_BASE_SIGNAL), risk_score=95.0)
    assert result is not None, "Module désactivé → signal doit passer"
    assert result["score"] == 8
    force_enable()   # reset


def test_factor_boundary_at_block_threshold():
    """Exactement à RISK_BLOCK (90) → bloqué."""
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=90.0)
    assert result is None


def test_factor_just_below_block():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=89.9)
    assert result is not None
    assert result["risk_factor"] < 1.0


def test_risk_level_in_output():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=40.0)
    assert result is not None
    assert "risk_level" in result
    assert result["risk_level"] in ("CALM", "LOW", "MEDIUM", "HIGH", "EXTREME")


def test_modulation_stats():
    force_enable()
    stats = get_modulation_stats()
    assert "active" in stats
    assert "total" in stats
    assert stats["active"] is True


def test_score_never_negative():
    force_enable()
    signal_low = dict(_BASE_SIGNAL)
    signal_low["score"] = 1
    result = modulate(signal_low, risk_score=65.0)
    if result:
        assert result["score"] >= 0


if __name__ == "__main__":
    test_pass_through_low_risk()
    test_reduce_medium_risk()
    test_block_high_risk()
    test_block_extreme_risk()
    test_passthrough_when_disabled()
    test_factor_boundary_at_block_threshold()
    test_factor_just_below_block()
    test_risk_level_in_output()
    test_modulation_stats()
    test_score_never_negative()
    print("✅ Tous les tests modulator passent")
