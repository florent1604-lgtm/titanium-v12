"""Raffinement du point d'entrée par TF inférieurs (Florent 25/07)."""
import numpy as np
import pandas as pd

from core import entry_refine as er


def _df(highs, lows, opens=None, closes=None):
    n = len(highs)
    opens = opens if opens is not None else [(h + l) / 2 for h, l in zip(highs, lows)]
    closes = closes if closes is not None else [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "v": [1.0] * n})


def test_neutre_si_pas_de_direction():
    r = er.refine("X", 0, None, None, atr_ref=1.0, ref_price=100.0, base_sl_mult=1.5)
    assert r["applied"] is False and r["sl_mult"] == 1.5 and r["refine_score"] == 0.0


def test_neutre_si_donnees_invalides():
    r = er.refine("X", 1, None, None, atr_ref=0.0, ref_price=0.0, base_sl_mult=1.5)
    assert r["applied"] is False and r["sl_mult"] == 1.5


def test_sl_resserre_sur_swing_m5_long():
    # Descente puis remontée : un swing low net juste sous le prix courant → SL serré.
    highs = [110, 109, 108, 107, 106, 105, 104, 103.5, 104, 105, 106, 107]
    lows =  [109, 108, 107, 106, 105, 104, 103, 102.0, 103, 104, 105, 106]
    df = _df(highs, lows)
    ref_price = 106.0
    r = er.refine("X", +1, df, None, atr_ref=2.0, ref_price=ref_price, base_sl_mult=1.5,
                  sl_floor_frac=0.6)
    assert r["applied"] is True
    assert r["sl_anchor"] is not None and r["sl_anchor"] < ref_price
    # borné : jamais sous le plancher (0.6*1.5=0.9) ni au-dessus de la base (1.5)
    assert 0.9 - 1e-6 <= r["sl_mult"] <= 1.5 + 1e-6


def test_sl_jamais_sous_plancher():
    # Swing low collé au prix (distance ~0) → resserrement plafonné au plancher, pas 0.
    highs = [100.2, 100.1, 100.05, 100.1, 100.2]
    lows =  [100.0, 99.98, 99.99, 100.0, 100.05]
    df = _df(highs, lows)
    r = er.refine("X", +1, df, None, atr_ref=5.0, ref_price=100.1, base_sl_mult=1.5,
                  sl_floor_frac=0.6)
    if r["applied"]:
        assert r["sl_mult"] >= 0.9 - 1e-6      # plancher 0.6*1.5


def test_momentum_m1_ajoute_score():
    highs = [110, 109, 108, 107, 106, 105, 104, 103.5, 104, 105, 106, 107]
    lows =  [109, 108, 107, 106, 105, 104, 103, 102.0, 103, 104, 105, 106]
    m5 = _df(highs, lows)
    # M1 dernière bougie haussière (close>open) → +0.15 pour un long
    m1 = _df([100.5, 101.0], [99.5, 100.0], opens=[100.0, 100.1], closes=[100.2, 100.9])
    r = er.refine("X", +1, m5, m1, atr_ref=2.0, ref_price=106.0, base_sl_mult=1.5)
    assert r["refine_score"] >= 0.15
    assert "M1" in r["ltf"]


def test_fail_safe_sur_donnee_corrompue():
    # DataFrame sans colonnes attendues → pas d'exception, refinement neutre.
    bad = pd.DataFrame({"foo": [1, 2, 3]})
    r = er.refine("X", 1, bad, bad, atr_ref=1.0, ref_price=100.0, base_sl_mult=1.5)
    assert r["sl_mult"] == 1.5   # base inchangée
