from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_provider():
    # Réorg Phase 1.5 : mt5_provider a été déplacé vers ingestion/market/ (data/mt5_provider.py
    # n'est plus qu'un shim sans les attributs du module). On charge la vraie implémentation.
    path = Path("ingestion/market/mt5_provider.py").resolve()
    spec = importlib.util.spec_from_file_location("mt5_provider_status_test", path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("pandas")
    sys.modules["pandas"] = types.ModuleType("pandas")
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("pandas", None)
        else:
            sys.modules["pandas"] = previous
    return module


class _Account:
    login = 50061786
    server = "Axi-US50-Demo"
    currency = "USD"
    trade_mode = 0
    balance = 1000.0
    equity = 1013.68
    margin = 54.74
    margin_free = 958.94
    margin_level = 1851.8


class _Position:
    ticket = 74487765
    symbol = "EURUSD"
    type = 1
    volume = 0.24
    price_open = 1.14037
    price_current = 1.13980
    sl = 1.14245
    tp = 1.13717
    profit = 13.68
    magic = 500786
    comment = "titanium-demo"


class _FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    POSITION_TYPE_BUY = 0
    account_calls = 0

    @staticmethod
    def account_info():
        _FakeMT5.account_calls += 1
        return _Account()

    @staticmethod
    def positions_get():
        return (_Position(),)


def test_account_snapshot_exposes_demo_execution_activity(monkeypatch):
    provider = _load_provider()
    monkeypatch.setattr(provider, "MT5_AVAILABLE", True)
    monkeypatch.setattr(provider, "_initialized", True)
    monkeypatch.setattr(provider, "mt5", _FakeMT5())
    monkeypatch.setenv("DEMO_EXEC_ENABLED", "1")
    _FakeMT5.account_calls = 0

    snapshot = provider.account_snapshot()
    cached = provider.account_snapshot()

    assert snapshot["connected"] is True
    assert snapshot["mode"] == "demo"
    assert snapshot["demo_execution_enabled"] is True
    assert snapshot["position_count"] == 1
    assert snapshot["floating_pnl"] == 13.68
    assert snapshot["positions"][0]["symbol"] == "EURUSD"
    assert snapshot["positions"][0]["side"] == "short"
    assert "DÉMO" in snapshot["note"]
    assert cached == snapshot
    assert _FakeMT5.account_calls == 1


def test_orbe_renders_demo_mode_and_positions_from_mt5_snapshot():
    html = Path("titanium_orbe.html").read_text(encoding="utf-8")
    assert 'mt5.mode==="demo"&&mt5.demo_execution_enabled' in html
    assert "MT5 DÉMO · ${demoCount} POS" in html
    assert "EXÉCUTION DÉMO MT5" in html
    assert "MT5 + MIROIR DÉMO" not in html  # libellé stable attendu ci-dessous
    assert "MOTEURS PAPER + MIROIR DÉMO" in html
