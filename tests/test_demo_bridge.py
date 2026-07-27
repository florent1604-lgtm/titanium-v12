"""Étape D — pont moteurs→démo : désarmement + non-fatal + multi-position/actif."""
import asyncio
import os
import sys
import types
from execution import demo_bridge as db


class _Pos:
    """Position MT5 factice (type 0=buy/long, 1=sell/short ; comment encode |pN)."""
    def __init__(self, type_, comment):
        self.type = type_
        self.comment = comment


def _fake_mt5(positions):
    m = types.SimpleNamespace()
    # positions_get(symbol=…) → positions de ce symbole ; sans arg → global (non atteint
    # dans les branches de refus testées ici).
    m.positions_get = lambda symbol=None: list(positions)
    return m


def test_disarmed_returns_none(monkeypatch):
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "0")
    r = asyncio.run(db.place_demo_async("EURUSD", "long", atr=0.001))
    assert r is None


def test_pos_quality_and_side():
    assert db._pos_quality(_Pos(0, "titanium-conf|p4")) == 4
    assert db._pos_quality(_Pos(0, "vieux-commentaire")) == 0   # antérieur à la convention
    assert db._pos_side(_Pos(0, "x")) == "long"
    assert db._pos_side(_Pos(1, "x")) == "short"


def test_multi_position_cap_par_actif(monkeypatch):
    """Plafond DEMO_MAX_POS_PER_SYMBOL atteint → refus MAX_POS_PER_SYMBOL."""
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    monkeypatch.setenv("DEMO_MAX_POS_PER_SYMBOL", "3")
    monkeypatch.setitem(sys.modules, "MetaTrader5",
                        _fake_mt5([_Pos(0, "c|p2"), _Pos(0, "c|p3"), _Pos(0, "c|p4")]))
    r = db._place_sync("EURUSD", "long", 0.001, 1.5, 3.0, quality=5)
    assert r["sent"] is False and r["reason"].startswith("MAX_POS_PER_SYMBOL")


def test_multi_position_meme_sens_requis(monkeypatch):
    """Position opposée déjà ouverte → refus (pas de hedge stérile)."""
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    monkeypatch.setenv("DEMO_MAX_POS_PER_SYMBOL", "3")
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5([_Pos(1, "c|p2")]))  # short
    r = db._place_sync("EURUSD", "long", 0.001, 1.5, 3.0, quality=5)
    assert r["sent"] is False and "OPPOSITE_SIDE_OPEN" in r["reason"]


def test_multi_position_exige_setup_meilleur(monkeypatch):
    """Empilement refusé si le nouveau setup n'a PAS strictement plus de piliers."""
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    monkeypatch.setenv("DEMO_MAX_POS_PER_SYMBOL", "3")
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5([_Pos(0, "c|p4")]))  # long p4
    r = db._place_sync("EURUSD", "long", 0.001, 1.5, 3.0, quality=3)   # 3 <= 4
    assert r["sent"] is False and "NOT_BETTER_SETUP" in r["reason"]
    r2 = db._place_sync("EURUSD", "long", 0.001, 1.5, 3.0, quality=4)  # 4 <= 4 (pas meilleur)
    assert r2["sent"] is False and "NOT_BETTER_SETUP" in r2["reason"]


def test_error_is_non_fatal(monkeypatch):
    # armé mais _place_sync lève (MT5 absent en test) → None, pas d'exception
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    def boom(*a, **k): raise RuntimeError("pas de MT5 en test")
    monkeypatch.setattr(db, "_place_sync", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r = asyncio.run(db.place_demo_async("EURUSD", "long", atr=0.001))
    assert r is None
