"""OHLCV Binance sync (ajustement crypto) : parsing pur + mapping MT5→Binance."""
import pandas as pd
import pytest

from data import binance_ohlcv as bo


def test_parse_klines_ok():
    raw = [[1_700_000_000_000, "100", "101", "99", "100.5", "12.3", 1_700_000_059_999],
           [1_700_000_060_000, "100.5", "102", "100", "101.5", "10.0", 1_700_000_119_999]]
    df = bo.parse_klines(raw)
    assert list(df.columns) == ["open", "high", "low", "close", "v"] and len(df) == 2
    assert isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None
    assert float(df["close"].iloc[-1]) == 101.5 and float(df["v"].iloc[0]) == 12.3


def test_parse_klines_invalide():
    assert bo.parse_klines([]) is None
    assert bo.parse_klines("pas une liste") is None
    assert bo.parse_klines([["seulement_deux", "champs"]]) is None


def test_mt5_to_binance():
    assert bo.mt5_to_binance("BTCUSD") == "BTC/USDT"
    assert bo.mt5_to_binance("ethusd") == "ETH/USDT"      # insensible à la casse
    assert bo.mt5_to_binance("XAUUSD") is None            # pas du crypto → pas de référence


@pytest.mark.parametrize("bad_close", [float("nan"), float("inf"), 0.0, -1.0])
def test_reference_close_rejette_prix_invalide(monkeypatch, bad_close):
    frame = pd.DataFrame({"close": [bad_close]})
    monkeypatch.setattr(bo, "get_ohlcv", lambda *a, **k: frame)

    assert bo.reference_close("BTCUSD") is None
