"""Filtre de tendance : ne pas fader une tendance H4 nette (Florent 25/07)."""
import numpy as np
import pandas as pd

from core.confluence_demo_engine import _counter_trend_block


def _htf_uptrend(n=260, start=100.0, step=0.5):
    """Série clairement haussière (prix >> EMA200)."""
    close = np.array([start + i * step for i in range(n)], dtype=float)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close})


def _htf_downtrend(n=260, start=200.0, step=0.5):
    close = np.array([start - i * step for i in range(n)], dtype=float)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close})


def _htf_flat(n=260, base=100.0):
    close = np.array([base + (0.5 if i % 2 else -0.5) for i in range(n)], dtype=float)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close})


def test_short_contre_hausse_nette_est_bloque():
    df = _htf_uptrend()
    # trend=+1 (prix au-dessus EMA200), setup SHORT (-1) → contre-tendance nette → bloqué
    assert _counter_trend_block({"trend": 1}, -1, df, atr=1.0, min_atr_dist=0.25) is True


def test_long_contre_baisse_nette_est_bloque():
    df = _htf_downtrend()
    assert _counter_trend_block({"trend": -1}, +1, df, atr=1.0, min_atr_dist=0.25) is True


def test_continuation_non_bloquee():
    df = _htf_uptrend()
    # setup LONG dans une tendance haussière → continuation → autorisé
    assert _counter_trend_block({"trend": 1}, +1, df, atr=1.0, min_atr_dist=0.25) is False


def test_range_non_bloque():
    df = _htf_flat()
    # tendance neutre (trend=0) → retour-moyenne autorisé des deux côtés
    assert _counter_trend_block({"trend": 0}, -1, df, atr=1.0, min_atr_dist=0.25) is False
    assert _counter_trend_block({"trend": 0}, +1, df, atr=1.0, min_atr_dist=0.25) is False


def test_contre_tendance_faible_non_bloquee():
    # prix TRÈS proche de l'EMA200 → tendance pas assez nette → on n'impose rien (min_atr élevé)
    df = _htf_uptrend()
    assert _counter_trend_block({"trend": 1}, -1, df, atr=1.0, min_atr_dist=10_000.0) is False


def test_fail_safe_donnees_manquantes():
    assert _counter_trend_block({"trend": 1}, -1, None, atr=1.0, min_atr_dist=0.25) is False
    assert _counter_trend_block({}, -1, _htf_uptrend(), atr=None, min_atr_dist=0.25) is False
