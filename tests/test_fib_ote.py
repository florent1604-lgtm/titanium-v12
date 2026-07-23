"""Fibonacci OTE : golden zone d'une impulsion + invalidation si structure cassée."""
import numpy as np
import pandas as pd

from core import fib_ote as fo


def _leg_up():
    """Swing bas ~100 -> impulsion -> swing haut 110, puis pullback COURT (pas
    encore de nouveau swing bas confirmé) : la dernière jambe reste haussière."""
    lows  = [103, 102, 101, 100, 100.5, 102, 104, 106, 108, 109, 108.5, 108, 107, 106.5, 106.6]
    highs = [103.3, 102.3, 101.3, 100.3, 101, 102.5, 104.5, 106.5, 108.5, 110, 109, 108.5, 107.5, 107, 107.1]
    return pd.DataFrame({"high": highs, "low": lows, "close": lows})


def test_detecte_impulsion_haussiere_et_ote():
    fz = fo.compute_fib_ote(_leg_up(), k=2)
    assert fz is not None and fz.direction == +1
    # OTE entre 0.618 et 0.786 du move 100->110 => ~101.4..103.8
    lo, hi = sorted((fz.ote_low, fz.ote_high))
    assert 101.0 < lo < hi < 104.5
    assert lo < fz.golden < hi              # 0.705 au coeur


def test_in_ote_et_invalidation():
    fz = fo.compute_fib_ote(_leg_up(), k=2)
    assert fz.in_ote(fz.golden)             # le coeur est dans la zone
    assert not fz.in_ote(109.0)             # trop haut = pas un pullback
    # invalidation : sous l'origine de l'impulsion (100)
    assert fz.invalidated(99.0)
    assert not fz.invalidated(102.0)


def test_entry_context():
    df = _leg_up()
    ctx = fo.entry_context(df, price=None if False else float(fo.compute_fib_ote(df, k=2).golden), k=2)
    assert ctx["available"] and ctx["in_ote"] and not ctx["invalidated"]


def test_failsafe():
    assert fo.compute_fib_ote(None) is None
    assert fo.compute_fib_ote(pd.DataFrame({"high": [1, 2, 3], "low": [1, 2, 3]})) is None


def test_rejects_invalid_parameters_and_market_data():
    df = _leg_up()
    assert fo.compute_fib_ote(df, k=0) is None
    bad = df.copy()
    bad.loc[5, "high"] = np.nan
    assert fo.compute_fib_ote(bad, k=2) is None
    bad = df.copy()
    bad.loc[5, "low"] = bad.loc[5, "high"] + 1.0
    assert fo.compute_fib_ote(bad, k=2) is None


def test_entry_context_rejects_non_finite_price():
    assert fo.entry_context(_leg_up(), price=np.nan, k=2) == {"available": False}
