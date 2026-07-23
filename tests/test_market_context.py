"""Adaptateur données réelles → contexte émotion : fail-safe, fraîcheur, features
bougies, routage crypto/MT5. Injection de RawInputs (aucun bot vivant requis)."""
import pandas as pd

from emotion import market_context as mc
from emotion import emotion_engine as em


def _df(ranges, vols, closes):
    """Construit un OHLCV synthétique (open/high/low/close/v) chronologique."""
    rows = []
    for rg, v, c in zip(ranges, vols, closes):
        rows.append({"open": c - rg * 0.3, "high": c + rg * 0.5,
                     "low": c - rg * 0.5, "close": c, "v": v})
    return pd.DataFrame(rows)


def test_failsafe_omits_absent_sources():
    ctx = mc.assemble_context(mc.RawInputs(macro_risk=80.0, now=1000.0))
    assert ctx == {"macro_risk": 80.0, "max_age_s": 30.0}   # rien d'inventé
    assert "delta_volume" not in ctx and "source_age_s" not in ctx


def test_nan_inputs_are_omitted_not_extreme():
    # red-team Codex P0-1 : _clamp de l'adaptateur transformait NaN en +1
    ctx = mc.assemble_context(mc.RawInputs(delta_pct=float("nan"), funding=float("inf"),
                                           long_short_ratio=float("nan"), macro_risk=50.0,
                                           now=1000.0))
    assert "delta_volume" not in ctx and "funding_rate" not in ctx
    assert "long_short_ratio" not in ctx and ctx["macro_risk"] == 50.0
    # bout en bout : un NaN ne crée pas de fausse euphorie
    st = mc.emotion_for("BTC/USDT", raw=mc.RawInputs(delta_pct=float("nan"), now=1000.0))
    assert not st.available


def test_source_age_from_freshest_signal():
    raw = mc.RawInputs(delta_pct=0.4, delta_ts=970.0, now=1000.0)
    ctx = mc.assemble_context(raw)
    assert ctx["delta_volume"] == 0.4 and ctx["source_age_s"] == 30.0


def test_stale_data_flows_to_emotion_confidence():
    fresh = mc.emotion_for("BTC/USDT",
                           raw=mc.RawInputs(delta_pct=0.5, delta_ts=999.0, now=1000.0))
    old = mc.emotion_for("BTC/USDT", max_age_s=15.0,
                         raw=mc.RawInputs(delta_pct=0.5, delta_ts=900.0, now=1000.0))
    assert not fresh.stale and old.stale and old.confidence < fresh.confidence


def test_candle_features_capture_spike_and_momentum():
    n = 30
    ranges = [1.0] * (n - 1) + [5.0]           # pic de volatilité sur la dernière barre
    vols = [100.0] * (n - 1) + [400.0]         # afflux de volume ×4
    closes = [100.0] * (n - 7) + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    atr_z, vol_s, mom = mc._candle_features(_df(ranges, vols, closes))
    assert atr_z is not None and atr_z > 2.0   # anormalement volatile
    assert vol_s == 1.0                        # surge saturé
    assert mom is not None and mom > 0.5       # avidité qui monte


def test_candle_features_insufficient_history():
    small = _df([1.0, 1.0], [100.0, 100.0], [100.0, 100.5])
    assert mc._candle_features(small) == (None, None, None)


def test_mt5_body_pressure_reads_buying():
    # bougies qui clôturent près du haut = pression ACHETEUR
    df = _df([2.0] * 6, [100.0] * 6, [100, 101, 102, 103, 104, 105])
    # forcer close = high (achat franc)
    df["close"] = df["high"]
    assert mc._candle_body_pressure(df) > 0.4


def test_mt5_tick_iso_timestamp_feeds_freshness(monkeypatch):
    """get_tick renvoie `ts` en ISO-8601, pas un epoch. Régression : float(ts) levait
    une exception avalée → delta_ts=None → STALE jamais déclenché sur MT5."""
    import types
    from datetime import datetime, timezone

    df = _df([1.0] * 10, [100.0] * 10, [100.0] * 10)
    signed_ts = datetime.fromtimestamp(900.0, tz=timezone.utc).isoformat()
    fake = types.SimpleNamespace(
        get_ohlcv=lambda symbol, tf="M15", n=120: df,
        get_tick=lambda symbol: {"bid": 1.0, "ask": 1.1, "ts": signed_ts, "stale": False},
    )
    monkeypatch.setitem(__import__("sys").modules, "data.mt5_provider", fake)

    raw = mc.live_raw_mt5("US50")
    assert raw.delta_ts == 900.0                      # ISO correctement parsé en epoch
    ctx = mc.assemble_context(mc.RawInputs(delta_ts=raw.delta_ts, delta_pct=raw.delta_pct,
                                           candles=df, now=1000.0), max_age_s=60.0)
    assert ctx["source_age_s"] == 100.0               # la fraîcheur remonte enfin
    assert mc.emotion_for("US50", raw=mc.RawInputs(delta_ts=900.0, delta_pct=0.5,
                                                   now=1000.0), max_age_s=60.0).stale


def test_routing_crypto_vs_mt5():
    assert mc._is_crypto("BTC/USDT") and not mc._is_crypto("US50")
    assert not mc._is_crypto("XAUUSD") and not mc._is_crypto("EURUSD")


def test_emotion_for_end_to_end_with_injected_raw():
    # avidité forte + haute énergie via bougies → état exploitable
    n = 30
    df = _df([1.0] * (n - 1) + [4.0], [100.0] * (n - 1) + [350.0],
             [100.0] * (n - 7) + [100, 101, 102, 103, 104, 105, 106])
    raw = mc.RawInputs(delta_pct=0.8, delta_ts=1000.0, funding=0.0005,
                       long_short_ratio=2.5, macro_risk=20.0, candles=df, now=1000.0)
    st = mc.emotion_for("BTC/USDT", raw=raw)
    assert st.available and st.valence > 0 and st.arousal > 0
    assert st.label in (em.OPTIMISM, em.THRILL, em.EUPHORIA, em.COMPLACENCY)
