"""Résilience du connecteur MT5 sans connexion au terminal réel."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from ingestion.market import mt5_provider as mp


class _FakeMT5:
    TIMEFRAME_H1 = 60
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440

    def __init__(self, *, select_ok: bool = True, init_ok: bool = True):
        self.select_ok = select_ok
        self.init_ok = init_ok
        self.select_calls = 0
        self.initialize_calls = 0
        self.copy_calls = 0
        self.terminal = SimpleNamespace(connected=True)

    def symbol_select(self, symbol, enabled):
        self.select_calls += 1
        time.sleep(0.005)
        return self.select_ok

    def last_error(self):
        return (4302, "Market closed")

    def terminal_info(self):
        return self.terminal

    def initialize(self):
        self.initialize_calls += 1
        return self.init_ok

    def account_info(self):
        return SimpleNamespace(login=50061786, server="Axi-US50-Demo")

    def copy_rates_from_pos(self, *args):
        self.copy_calls += 1
        raise AssertionError("la lecture ne doit pas suivre un symbol_select refusé")


def _reset_provider(monkeypatch, fake: _FakeMT5) -> None:
    monkeypatch.setattr(mp, "MT5_AVAILABLE", True)
    monkeypatch.setattr(mp, "mt5", fake)
    monkeypatch.setattr(mp, "_selected", set())
    monkeypatch.setattr(mp, "_initialized", True)
    monkeypatch.setattr(mp, "_init_failures", 0, raising=False)
    monkeypatch.setattr(mp, "_init_next_retry_at", 0.0, raising=False)


def test_symbol_selection_is_atomic_across_threads(monkeypatch):
    fake = _FakeMT5()
    _reset_provider(monkeypatch, fake)

    threads = [
        threading.Thread(target=mp._ensure_symbol, args=("BTCUSD",))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert all(not thread.is_alive() for thread in threads)
    assert fake.select_calls == 1
    assert mp._selected == {"BTCUSD"}


def test_symbol_select_failure_is_explicit_inside_provider(monkeypatch):
    fake = _FakeMT5(select_ok=False)
    _reset_provider(monkeypatch, fake)

    try:
        mp._ensure_symbol("UNKNOWN")
    except mp.MT5SymbolError as exc:
        assert "UNKNOWN" in str(exc)
        assert "4302" in str(exc)
    else:
        raise AssertionError("MT5SymbolError attendue")

    assert "UNKNOWN" not in mp._selected


def test_public_rates_contract_stays_optional_on_symbol_failure(monkeypatch):
    fake = _FakeMT5(select_ok=False)
    _reset_provider(monkeypatch, fake)

    assert mp.get_rates("UNKNOWN", "H1", 10) is None
    assert fake.copy_calls == 0


def test_initialized_session_is_revalidated_and_reconnected(monkeypatch):
    fake = _FakeMT5(init_ok=True)
    fake.terminal = None
    _reset_provider(monkeypatch, fake)

    assert mp.ensure_init() is True
    assert fake.initialize_calls == 1


def test_failed_initialization_is_backed_off_without_sleep(monkeypatch):
    fake = _FakeMT5(init_ok=False)
    _reset_provider(monkeypatch, fake)
    mp._initialized = False
    monkeypatch.setattr(mp.time, "monotonic", lambda: 100.0)

    assert mp.ensure_init() is False
    assert mp.ensure_init() is False
    assert fake.initialize_calls == 1


def test_fast_ticks_skip_unselectable_symbol(monkeypatch):
    class _MixedMT5(_FakeMT5):
        def symbol_select(self, symbol, enabled):
            self.select_calls += 1
            return symbol != "BAD"

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(
                bid=100.0,
                ask=100.1,
                time_msc=123456789,
            )

    fake = _MixedMT5()
    _reset_provider(monkeypatch, fake)

    result = mp.get_ticks_fast(["GOOD", "BAD"])

    assert set(result) == {"GOOD"}
    assert "BAD" not in mp._selected
