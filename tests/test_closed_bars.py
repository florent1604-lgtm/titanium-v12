"""Contrat closed_bars : jamais décider sur une bougie en formation (P0 Codex)."""
from datetime import datetime, timezone

import pandas as pd

from core import closed_bars as cb


def _df(n=5, tf_min=60, start="2026-07-16 10:00"):
    idx = pd.date_range(start, periods=n, freq=f"{tf_min}min", tz="UTC")
    return pd.DataFrame({"open": range(n), "high": range(n), "low": range(n),
                         "close": range(n), "v": [1] * n}, index=idx)


def test_derniere_bougie_en_formation_retiree():
    df = _df(n=5, tf_min=60)                 # dernière ouvre à 14:00, close à 15:00
    now = datetime(2026, 7, 16, 14, 30, tzinfo=timezone.utc)   # 14:30 : pas encore close
    out = cb.closed_only(df, "H1", now=now)
    assert len(out) == 4 and out.index[-1] == df.index[-2]


def test_derniere_bougie_close_conservee():
    df = _df(n=5, tf_min=60)
    now = datetime(2026, 7, 16, 15, 1, tzinfo=timezone.utc)     # 15:01 : close à 15:00 passée
    out = cb.closed_only(df, "H1", now=now)
    assert len(out) == 5


def test_invariant_bougie_ouverte_ne_change_rien():
    # changer la dernière bougie (en formation) ne doit pas changer la sortie
    now = datetime(2026, 7, 16, 14, 30, tzinfo=timezone.utc)
    a = _df(n=5, tf_min=60); b = a.copy()
    b.iloc[-1, :] = [999, 999, 999, 999, 999]
    assert cb.closed_only(a, "H1", now=now).equals(cb.closed_only(b, "H1", now=now))


def test_fail_closed_tf_inconnu():
    assert cb.closed_only(_df(), "TF_BIDON") is None


def test_fail_closed_index_non_temporel():
    df = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "v": [1, 1]})
    assert cb.closed_only(df, "H1") is None


def test_assert_closed_leve_si_vide():
    df = _df(n=1, tf_min=60)
    now = datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc)     # bougie unique pas close
    import pytest
    with pytest.raises(ValueError):
        cb.assert_closed(df, "H1", now=now)


# ── validate_frame : sanité + fraîcheur (data_valid n'est plus sur-vendu) ──────

def _ohlc(n=30, tf_min=60, start="2026-07-16 00:00"):
    idx = pd.date_range(start, periods=n, freq=f"{tf_min}min", tz="UTC")
    return pd.DataFrame({"open": [10.0] * n, "high": [10.5] * n, "low": [9.5] * n,
                         "close": [10.1] * n}, index=idx)


def test_validate_frame_ok():
    df = _ohlc()
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)     # dernière bougie récente
    ok, code = cb.validate_frame(df, "H1", now=now, min_len=10)
    assert ok and code == "OK"


def test_validate_frame_index_non_monotone():
    df = _ohlc()
    df = df.iloc[::-1]                                          # index décroissant
    ok, code = cb.validate_frame(df, "H1")
    assert not ok and code == "INDEX_NOT_MONOTONIC"


def test_validate_frame_doublons_index():
    df = _ohlc(n=5)
    df = pd.concat([df, df.iloc[[-1]]])                         # timestamp dupliqué
    ok, code = cb.validate_frame(df, "H1")
    assert not ok and code == "INDEX_DUPLICATES"


def test_validate_frame_ohlc_incoherent():
    df = _ohlc(n=5)
    df.iloc[-1, df.columns.get_loc("high")] = 8.0              # high < low
    ok, code = cb.validate_frame(df, "H1")
    assert not ok and code == "INCOHERENT_OHLC"


def test_validate_frame_non_fini():
    df = _ohlc(n=5)
    df.iloc[-1, df.columns.get_loc("close")] = float("nan")
    ok, code = cb.validate_frame(df, "H1")
    assert not ok and code == "NON_FINITE_OHLC"


def test_validate_frame_controle_tout_ce_que_les_detecteurs_peuvent_lire():
    df = _ohlc(n=250)
    df.iloc[0, df.columns.get_loc("close")] = float("nan")
    ok, code = cb.validate_frame(df, "H1")
    assert not ok and code == "NON_FINITE_OHLC"


def test_validate_frame_stale():
    df = _ohlc(n=30, start="2026-07-16 00:00")                 # dernière bougie ~29h
    now = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)     # 4 jours plus tard → gelé
    ok, code = cb.validate_frame(df, "H1", now=now)
    assert not ok and code == "STALE"
