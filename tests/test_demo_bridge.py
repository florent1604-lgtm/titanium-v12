"""Étape D — pont moteurs→démo : désarmement + non-fatal."""
import asyncio
import os
from execution import demo_bridge as db


def test_disarmed_returns_none(monkeypatch):
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "0")
    r = asyncio.run(db.place_demo_async("EURUSD", "long", atr=0.001))
    assert r is None


def test_error_is_non_fatal(monkeypatch):
    # armé mais _place_sync lève (MT5 absent en test) → None, pas d'exception
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    def boom(*a, **k): raise RuntimeError("pas de MT5 en test")
    monkeypatch.setattr(db, "_place_sync", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r = asyncio.run(db.place_demo_async("EURUSD", "long", atr=0.001))
    assert r is None
