"""tests/test_guards.py — Tests du guard pipeline pré-exécution (Phase G).

Vérifie : stop-loss obligatoire, whitelist symbole, exposition corrélée (flag off par
défaut), et le fail-safe — une garde qui ne peut pas s'évaluer BLOQUE, ne force jamais
un trade.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

from execution import guards


def _signal(**over):
    base = {"symbol": "BTC/USDT", "side": "ACHAT", "sl": 90000.0}
    base.update(over)
    return base


def test_pass_when_valid():
    result = guards.run_guards(_signal(), "BTC/USDT", {}, capital=1000.0)
    assert result.passed


def test_stop_loss_required_blocks_without_sl():
    result = guards.run_guards(_signal(sl=0), "BTC/USDT", {}, capital=1000.0)
    assert not result.passed
    assert result.guard == "stop_loss_required"


def test_symbol_whitelist_blocks_unknown_symbol():
    result = guards.run_guards(_signal(symbol="DOGE/USDT"), "DOGE/USDT", {}, capital=1000.0)
    assert not result.passed
    assert result.guard == "symbol_whitelist"


def test_fail_safe_blocks_on_exception():
    """Une garde qui lève une exception BLOQUE l'ordre — jamais l'inverse."""
    with patch.object(guards, "_guard_whitelist", side_effect=RuntimeError("boom")):
        result = guards.run_guards(_signal(), "BTC/USDT", {}, capital=1000.0)
    assert not result.passed
    assert result.guard.startswith("guard_eval_error:")


def test_correlated_exposure_off_by_default():
    """GUARD_CORRELATED_EXPOSURE_ENABLED=0 par défaut — ne bloque jamais, même à forte exposition."""
    open_positions = {"BTC/USDT": 900.0}
    result = guards.run_guards(_signal(), "BTC/USDT", open_positions, capital=1000.0)
    assert result.passed


def test_correlated_exposure_blocks_when_enabled_and_over_threshold():
    with patch.object(guards, "GUARD_CORRELATED_EXPOSURE_ENABLED", True), \
         patch.object(guards, "GUARD_CORRELATED_EXPOSURE_MAX_PCT", 0.30):
        open_positions = {"BTC/USDT": 500.0}  # 50% du capital > seuil 30%
        result = guards.run_guards(_signal(), "BTC/USDT", open_positions, capital=1000.0)
    assert not result.passed
    assert result.guard == "correlated_exposure"


def test_correlated_exposure_uses_cluster_not_only_exact_symbol():
    """L'exposition corrélée se cumule par cluster (SYM_CLUSTER), pas seulement le symbole exact."""
    with patch.object(guards, "GUARD_CORRELATED_EXPOSURE_ENABLED", True), \
         patch.object(guards, "GUARD_CORRELATED_EXPOSURE_MAX_PCT", 0.30), \
         patch.object(guards, "SYM_CLUSTER", {"BTC/USDT": "crypto", "ETH/USDT": "crypto"}):
        open_positions = {"ETH/USDT": 500.0}
        result = guards.run_guards(_signal(symbol="BTC/USDT"), "BTC/USDT", open_positions, capital=1000.0)
    assert not result.passed
    assert result.guard == "correlated_exposure"
