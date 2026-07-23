"""Profil de volume : VPOC au prix le plus échangé, value area ~70%, HVN/LVN."""
import numpy as np
import pandas as pd

from core import volume_profile as vp


def _df_concentrated():
    """Prix qui passe l'essentiel de son temps (volume) autour de 100."""
    rng = np.random.default_rng(1)
    rows = []
    for _ in range(400):
        # 80% du temps collé à 100 (fort volume), 20% en excursion
        if rng.random() < 0.8:
            base = 100 + rng.normal(0, 0.3)
            vol = rng.uniform(80, 120)
        else:
            base = 100 + rng.normal(0, 3.0)
            vol = rng.uniform(5, 20)
        h = base + abs(rng.normal(0, 0.2)); l = base - abs(rng.normal(0, 0.2))
        rows.append({"high": h, "low": l, "close": base, "v": vol})
    return pd.DataFrame(rows)


def test_vpoc_at_most_traded_price():
    prof = vp.compute_profile(_df_concentrated(), bins=60)
    assert prof is not None
    assert 99.0 <= prof.vpoc <= 101.0            # le juste prix ~100
    assert prof.val < prof.vpoc < prof.vah       # value area encadre le POC


def test_value_area_contains_most_volume():
    prof = vp.compute_profile(_df_concentrated(), bins=60)
    tot = sum(prof.volumes)
    inside = sum(v for c, v in zip(prof.prices, prof.volumes) if prof.val <= c <= prof.vah)
    assert 0.60 <= inside / tot <= 0.85          # ~70% ciblé


def test_hvn_near_vpoc():
    prof = vp.compute_profile(_df_concentrated(), bins=60)
    assert prof.hvn, "au moins un nœud de forte acceptation"
    assert any(abs(h - prof.vpoc) < 2.0 for h in prof.hvn)


def test_entry_context_on_fair_price():
    df = _df_concentrated()
    ctx = vp.entry_context(df, price=100.0, window=400)
    assert ctx["available"] and ctx["in_value_area"] and ctx["on_fair_price_zone"]
    far = vp.entry_context(df, price=115.0, window=400)
    assert not far["in_value_area"]


def test_failsafe():
    assert vp.compute_profile(None) is None
    assert vp.compute_profile(pd.DataFrame({"high": [1, 2], "low": [1, 2], "v": [1, 1]})) is None


def test_rejects_invalid_parameters_and_market_data():
    df = _df_concentrated()
    assert vp.compute_profile(df, bins=0) is None
    assert vp.compute_profile(df, value_area_pct=0.0) is None
    assert vp.compute_profile(df, value_area_pct=1.1) is None

    bad = df.copy()
    bad.loc[20, "high"] = np.nan
    assert vp.compute_profile(bad) is None
    bad = df.copy()
    bad.loc[20, "low"] = bad.loc[20, "high"] + 1.0
    assert vp.compute_profile(bad) is None
    bad = df.copy()
    bad.loc[20, "v"] = -1.0
    assert vp.compute_profile(bad) is None


def test_entry_context_rejects_non_finite_price():
    assert vp.entry_context(_df_concentrated(), price=np.nan) == {"available": False}
