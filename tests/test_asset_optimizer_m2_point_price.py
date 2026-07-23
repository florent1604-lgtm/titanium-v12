from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools import asset_optimizer_m2 as optimizer


def _account() -> SimpleNamespace:
    return SimpleNamespace(
        login=optimizer.DEMO_LOGIN,
        balance=10_000.0,
        currency="EUR",
    )


def _symbol_info(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "point": 0.01,
        "trade_tick_size": 0.01,
        "trade_contract_size": 100_000.0,
        "currency_base": "USD",
        "currency_profit": "USD",
        "digits": 2,
        "bid": 100.0,
        "ask": 100.2,
        "spread": 20,
        "path": "Crypto\\Test",
        "swap_mode": 1,
        "swap_long": -1.0,
        "swap_short": -1.0,
        "swap_rollover3days": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _tick(bid: float, ask: float) -> SimpleNamespace:
    return SimpleNamespace(bid=bid, ask=ask, last=0.0, time=1_700_000_000)


class _FakeMT5:
    SYMBOL_SWAP_MODE_POINTS = 1
    SYMBOL_SWAP_MODE_CURRENCY_SYMBOL = 2
    SYMBOL_SWAP_MODE_INTEREST_CURRENT = 5

    def __init__(
        self,
        info: SimpleNamespace,
        ticks: list[SimpleNamespace],
        *,
        selectable: bool = True,
    ) -> None:
        self._info = info
        self._ticks = list(ticks)
        self._last_tick = self._ticks[-1]
        self._selectable = selectable
        self.tick_calls = 0

    def account_info(self) -> SimpleNamespace:
        return _account()

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        return self._selectable

    def symbol_info(self, symbol: str) -> SimpleNamespace:
        return self._info

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace:
        self.tick_calls += 1
        if self._ticks:
            return self._ticks.pop(0)
        return self._last_tick


def test_cost_snapshot_uses_trade_tick_size_when_point_is_zero() -> None:
    mt5 = _FakeMT5(
        _symbol_info(point=0.0, trade_tick_size=0.01, digits=2),
        [_tick(100.0, 100.2)],
    )

    snapshot = optimizer._cost_snapshot(mt5, "TEST", 1.25, 0.0)

    assert snapshot["point"] == pytest.approx(0.01)
    assert snapshot["point_source"] == "trade_tick_size"


def test_cost_snapshot_uses_digits_when_point_and_tick_size_are_zero() -> None:
    mt5 = _FakeMT5(
        _symbol_info(point=0.0, trade_tick_size=0.0, digits=5),
        [_tick(1.12345, 1.12355)],
    )

    snapshot = optimizer._cost_snapshot(mt5, "TEST", 1.25, 0.0)

    assert snapshot["point"] == pytest.approx(0.00001)
    assert snapshot["point_source"] == "digits"


def test_cost_snapshot_retries_a_transient_zero_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    mt5 = _FakeMT5(
        _symbol_info(bid=0.0, ask=0.0),
        [_tick(0.0, 0.0), _tick(96.41, 96.61)],
    )
    monkeypatch.setattr(optimizer.time, "sleep", lambda _seconds: None)

    snapshot = optimizer._cost_snapshot(mt5, "AAVE-USD", 1.25, 0.0)

    assert snapshot["mid_price"] == pytest.approx(96.51)
    assert snapshot["quote_attempts"] == 2


def test_calibrate_asset_classifies_unusable_spec_separately(tmp_path) -> None:
    mt5 = _FakeMT5(
        _symbol_info(point=0.0, trade_tick_size=0.0, digits=-1, bid=0.0, ask=0.0),
        [_tick(0.0, 0.0)],
    )

    result = optimizer.calibrate_asset(
        mt5,
        "BROKEN",
        optimizer.datetime(2022, 1, 1, tzinfo=optimizer.timezone.utc),
        optimizer.datetime(2026, 1, 1, tzinfo=optimizer.timezone.utc),
        tmp_path,
        1.25,
        0.0,
        100,
        1.0,
    )

    assert result["status"] == "DATA_SPEC_INVALID"
    assert result["symbol"] == "BROKEN"
    assert "point" in str(result["reason"]).lower()


@pytest.mark.parametrize(
    ("swap_mode", "swap_long", "contract_size", "expected_mode"),
    [
        (5, -20.0, 1.0, "INTEREST_CURRENT"),
        (2, -25.0, 100_000.0, "CURRENCY_SYMBOL"),
    ],
)
def test_cost_snapshot_supports_both_remaining_axi_swap_modes(
    swap_mode: int,
    swap_long: float,
    contract_size: float,
    expected_mode: str,
) -> None:
    mt5 = _FakeMT5(
        _symbol_info(
            swap_mode=swap_mode,
            swap_long=swap_long,
            swap_short=swap_long,
            trade_contract_size=contract_size,
        ),
        [_tick(100.0, 100.2)],
    )

    snapshot = optimizer._cost_snapshot(mt5, "TEST", 1.25, 0.0)

    assert snapshot["swap_mode"] == expected_mode
    assert snapshot["swap_supported"] is True
    assert snapshot["trade_contract_size"] == pytest.approx(contract_size)
    assert snapshot["currency_base"] == "USD"
    assert snapshot["currency_profit"] == "USD"
