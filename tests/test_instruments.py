"""Référentiel d'instruments unifié (axe G) : mapping, venue, filtres — pur, sans réseau."""
from core import instruments as ins


def test_get_et_mapping_binance():
    btc = ins.get("btcusd")                      # insensible à la casse
    assert btc.symbol == "BTCUSD" and btc.venue == "crypto" and btc.binance == "BTC/USDT"
    assert ins.binance_ref("ETHUSD") == "ETH/USDT"
    assert ins.binance_ref("XAUUSD") is None     # pas de crypto → pas de référence Binance


def test_from_binance_inverse():
    assert ins.from_binance("BTC/USDT").symbol == "BTCUSD"
    assert ins.from_binance("sol/usdt").symbol == "SOLUSD"
    assert ins.from_binance("INCONNU/USDT") is None


def test_venue_et_defaut_failsafe():
    assert ins.venue_of("BTCUSD") == "crypto"
    assert ins.venue_of("EURUSD") == "cfd"
    assert ins.venue_of("SYMBOLE_INCONNU") == "cfd"     # fail-safe
    assert ins.is_known("US500") and not ins.is_known("US500.fs.x")


def test_filtres_symbols():
    crypto = ins.symbols(venue="crypto")
    assert "BTCUSD" in crypto and "EURUSD" not in crypto
    metaux = ins.symbols(kind="metal")
    assert set(metaux) == {"XAUUSD", "XAGUSD"}
    indices = ins.symbols(venue="cfd", kind="index")
    assert "NAS100.fs" in indices and "EURUSD" not in indices


def test_delegation_binance_ohlcv():
    # binance_ohlcv.mt5_to_binance délègue désormais au référentiel unique
    from data.binance_ohlcv import mt5_to_binance
    assert mt5_to_binance("BTCUSD") == "BTC/USDT"
    assert mt5_to_binance("XAUUSD") is None
