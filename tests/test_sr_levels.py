"""Niveaux S/R : un niveau retesté plusieurs fois est plus fort ; support/résistance."""
import numpy as np
import pandas as pd

from core import sr_levels as sr


def _df_double_top():
    """Le prix teste ~110 deux fois (résistance) et ~100 deux fois (support)."""
    seq = [100, 103, 106, 110, 107, 104, 100, 103, 107, 110, 106, 103, 102]
    highs = [s + 0.4 for s in seq]; lows = [s - 0.4 for s in seq]
    return pd.DataFrame({"high": highs, "low": lows, "close": seq})


def test_detecte_niveaux_multi_touches():
    levels = sr.compute_sr_levels(_df_double_top(), k=1, tol_pct=1.0)
    assert levels
    prices = [lv.price for lv in levels]
    assert any(108.5 <= p <= 111 for p in prices)     # résistance ~110
    assert any(99 <= p <= 101.5 for p in prices)      # support ~100


def test_touches_augmentent_la_force():
    levels = sr.compute_sr_levels(_df_double_top(), k=1, tol_pct=1.0)
    multi = [lv for lv in levels if lv.touches >= 2]
    assert multi, "au moins un niveau retesté"
    assert max(lv.strength for lv in multi) > 0.4


def test_support_vs_resistance_relatif_au_prix():
    df = _df_double_top()
    ctx = sr.entry_context(df, price=float(df["close"].iloc[-1]), k=1)
    assert ctx["available"]
    if ctx["nearest_support"] is not None:
        assert ctx["nearest_support"] <= df["close"].iloc[-1] + 1
    if ctx["nearest_resistance"] is not None:
        assert ctx["nearest_resistance"] >= df["close"].iloc[-1] - 1


def test_failsafe():
    assert sr.compute_sr_levels(None) == []


def test_rejects_invalid_parameters_and_market_data():
    df = _df_double_top()
    assert sr.compute_sr_levels(df, k=0) == []
    assert sr.compute_sr_levels(df, tol_pct=0.0) == []
    bad = df.copy()
    bad.loc[5, "high"] = np.nan
    assert sr.compute_sr_levels(bad, k=1) == []
    bad = df.copy()
    bad.loc[5, "low"] = bad.loc[5, "high"] + 1.0
    assert sr.compute_sr_levels(bad, k=1) == []


def test_entry_context_rejects_non_finite_price():
    assert sr.entry_context(_df_double_top(), price=np.nan, k=1) == {"available": False}
