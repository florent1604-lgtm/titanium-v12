"""Flux kline : le drapeau x=isClosed est le signal de clôture autoritaire."""
from data import binance_kline_feed as kf


def _msg(is_closed, close_ms=1_700_000_060_000):
    return {"s": "BTCUSDT", "k": {"t": 1_700_000_000_000, "T": close_ms, "i": "1m",
                                  "o": "100", "h": "101", "l": "99", "c": "100.5",
                                  "v": "12.3", "x": is_closed}}


def test_parse_bougie_fermee():
    c = kf.parse_kline_msg(_msg(True), recv_ms=1_700_000_060_040)
    assert c["is_closed"] is True and c["close"] == 100.5
    assert c["close_latency_ms"] == 40          # 40 ms après la clôture officielle


def test_parse_bougie_en_formation():
    c = kf.parse_kline_msg(_msg(False))
    assert c["is_closed"] is False and c["close_latency_ms"] is None


def test_ignore_message_non_kline():
    assert kf.parse_kline_msg({"e": "aggTrade", "p": "100"}) is None
    assert kf.parse_kline_msg({}) is None
    assert kf.parse_kline_msg("pas un dict") is None


def test_intervals_connus():
    assert kf.INTERVALS["M15"] == "15m" and kf.INTERVALS["H1"] == "1h"


def test_dedup_bougie_fermee_une_seule_fois():
    d = kf.CloseDedup()
    c = kf.parse_kline_msg(_msg(True, close_ms=1_700_000_060_000))
    assert d.accept(c) is True          # 1re clôture acceptée
    assert d.accept(c) is False         # doublon (reconnexion) ignoré


def test_dedup_hors_ordre_ignore():
    d = kf.CloseDedup()
    recent = kf.parse_kline_msg(_msg(True, close_ms=1_700_000_120_000))
    older = kf.parse_kline_msg(_msg(True, close_ms=1_700_000_060_000))
    assert d.accept(recent) is True
    assert d.accept(older) is False     # message en retard → refusé


def test_dedup_refuse_bougie_non_fermee():
    d = kf.CloseDedup()
    assert d.accept(kf.parse_kline_msg(_msg(False))) is False
    assert d.accept(None) is False


def test_dedup_ne_commit_quapres_traitement_reussi():
    d = kf.CloseDedup()
    c = kf.parse_kline_msg(_msg(True))
    assert d.is_new(c) is True
    assert d.is_new(c) is True       # callback en échec : la bougie reste rejouable
    assert d.commit(c) is True
    assert d.is_new(c) is False
