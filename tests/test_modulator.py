"""tests/test_modulator.py — Tests unitaires du SignalModulator."""
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
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=50.0)
    assert result is not None
    assert result["score"] < 8, f"Score devrait être réduit: {result['score']}"
    assert 0.5 <= result["risk_factor"] < 1.0
    assert result.get("score_original") == 8


def test_block_high_risk():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=75.0)
    assert result is None, f"Signal devrait être annulé à risk=75: {result}"


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
    force_enable()
    # Exactement à la limite → bloqué
    result = modulate(dict(_BASE_SIGNAL), risk_score=70.0)
    assert result is None


def test_factor_just_below_block():
    force_enable()
    result = modulate(dict(_BASE_SIGNAL), risk_score=69.9)
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
