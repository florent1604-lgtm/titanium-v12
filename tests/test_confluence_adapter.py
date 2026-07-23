"""Adaptateur détecteurs → feats : fail-closed (clôture + sanité + cohérence temporelle),
production d'un contrat valide, chaînage jusqu'aux portes ET."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import confluence_adapter as ca
from core import confluence_gate as cg


def _mk(end_ts, step_min, n):
    idx = pd.date_range(end=end_ts, periods=n, freq=f"{step_min}min", tz="UTC")
    base = np.linspace(100, 112, n)
    noise = np.sin(np.arange(n) / 5) * 0.5
    close = base + noise
    return pd.DataFrame({
        "open": close - 0.1, "high": close + 0.4, "low": close - 0.4,
        "close": close, "v": np.random.default_rng(3).uniform(50, 150, n),
    }, index=idx)


def _frames(now, n=120):
    """LTF (H1) + HTF (H4) qui clôturent au MÊME instant (bord H4) → temporellement alignées."""
    end = pd.Timestamp(now).floor("4h")
    return _mk(end - pd.Timedelta(hours=1), 60, n), _mk(end - pd.Timedelta(hours=4), 240, n)


def test_fail_closed_sur_tf_inconnue():
    df, _ = _frames(datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc))
    feats = ca.build_feats(df, df, price=110.0, symbol="BTC/USDT",
                           timeframe="TF_BIDON", htf_timeframe="H4")
    assert feats["data_valid"] is False


def test_fail_closed_sur_frame_incoherente():
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    ltf, htf = _frames(now)
    ltf.iloc[-1, ltf.columns.get_loc("high")] = 1.0        # high < low → INCOHERENT_OHLC
    feats = ca.build_feats(ltf, htf, price=110.0, symbol="BTC/USDT", timeframe="H1",
                           htf_timeframe="H4", now=now, run_emotion=False)
    assert feats["data_valid"] is False


def test_produit_un_contrat_exploitable_par_les_portes():
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)   # lundi, marché ouvert
    ltf, htf = _frames(now)
    feats = ca.build_feats(ltf, htf, price=float(ltf["close"].iloc[-1]),
                           symbol="BTC/USDT", timeframe="H1", htf_timeframe="H4",
                           venue="crypto", now=now, run_emotion=False)
    assert feats["data_valid"] is True
    for key in ("trend", "setup_side", "setup_family", "on_sr_level", "fair_value", "liquidity", "ote",
                "candle", "emotion", "cost", "strengths", "_trace"):
        assert key in feats
    # edge_ok reste INCONNU (None) tant que le labo n'a pas mesuré : plus de fail-open
    assert feats["cost"]["edge_ok"] is None
    # trace explicable : version + horodatage de décision + as-of alignés
    tr = feats["_trace"]
    assert tr["version"] and tr["decided_at"] and tr["as_of"]["htf_ltf_aligned"] is True
    # le contrat passe dans les portes sans exception (verdict quelconque)
    d = cg.evaluate(feats)
    assert d.verdict in ("ENTER", "WAIT", "BLOCK") and d.decision_id
    assert d.decided_at == tr["decided_at"]


def test_prod_ne_peut_pas_entrer_sans_edge_mais_demo_teste():
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    ltf, htf = _frames(now)
    feats = ca.build_feats(ltf, htf, price=float(ltf["close"].iloc[-1]),
                           symbol="BTC/USDT", timeframe="H1", htf_timeframe="H4",
                           venue="crypto", now=now, run_emotion=False)
    # PROD : edge inconnu → jamais ENTER (fail-closed)
    assert cg.evaluate(feats, require_edge=True).verdict != "ENTER"


def test_weekend_block_cfd_vendredi_soir():
    vend_soir = datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)   # vendredi 21h
    ltf, htf = _frames(vend_soir)
    feats = ca.build_feats(ltf, htf, price=float(ltf["close"].iloc[-1]), symbol="XAUUSD",
                           timeframe="H1", htf_timeframe="H4", venue="cfd",
                           now=vend_soir, run_emotion=False)
    assert feats["data_valid"] is True and feats["cost"]["weekend_block"] is True
    # crypto le même instant : jamais bloqué (spot 24/7)
    fc = ca.build_feats(ltf, htf, price=float(ltf["close"].iloc[-1]), symbol="BTC/USDT",
                        timeframe="H1", htf_timeframe="H4", venue="crypto",
                        now=vend_soir, run_emotion=False)
    assert fc["cost"]["weekend_block"] is False
