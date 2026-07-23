from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from validation.asset_simulation import (
    Bar,
    CostModel,
    SimulatedTrade,
    aggregate_daily_returns,
    bounded_bar_request_count,
    candidate_id,
    chunked_time_ranges,
    derive_rollover_multipliers,
    fastest_validated_style,
    normalize_mt5_category,
    simulate,
    split_calibration_window,
    summarize_trade_economics,
    swap_bps_per_rollover,
)


UTC = timezone.utc


def _bar(hour: int, *, signal: int = 0, open_: float = 100.0, high: float = 101.0,
         low: float = 99.0, close: float = 100.0, atr: float = 1.0) -> Bar:
    return Bar(datetime(2026, 1, 1, hour, tzinfo=UTC), open_, high, low, close, atr, signal)


def _zero_costs() -> CostModel:
    return CostModel(0.0, 0.0, 0.0, 0.0, 2)


def test_window_is_50_20_30_and_candidate_ids_are_stable():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=100)
    window = split_calibration_window(start, end)
    assert window.dev_end == start + timedelta(days=50)
    assert window.selection_end == start + timedelta(days=70)
    assert candidate_id("scalp", True, False, 1.5, (1.0, 1.5, 2.5)) == (
        "scalp.a1.r0.sl1.5.tp1-1.5-2.5"
    )


def test_mt5_bar_request_is_bounded_by_terminal_history_limit():
    start = datetime(2022, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 1, tzinfo=UTC)
    assert bounded_bar_request_count(start, end, 15, 100_000) == 60_000
    assert bounded_bar_request_count(start, start + timedelta(days=10), 60, 100_000) == 242


def test_mt5_chunk_ranges_cover_the_locked_window_backwards_without_gaps():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 1, tzinfo=UTC)
    chunks = chunked_time_ranges(start, end, chunk_days=240)
    assert chunks == (
        (datetime(2025, 5, 6, tzinfo=UTC), end),
        (start, datetime(2025, 5, 6, tzinfo=UTC)),
    )


def test_swap_conversion_supports_axi_interest_open_and_points():
    assert swap_bps_per_rollover("INTEREST_OPEN", -7.2, point=0.01, price=100.0) == pytest.approx(2.0)
    assert swap_bps_per_rollover("INTEREST_OPEN", 3.6, point=0.01, price=100.0) == pytest.approx(-1.0)
    assert swap_bps_per_rollover("POINTS", -10.0, point=0.01, price=100.0) == pytest.approx(10.0)


def test_interest_current_swap_uses_the_rollover_price_relative_to_entry() -> None:
    assert swap_bps_per_rollover(
        "INTEREST_CURRENT",
        -7.2,
        point=0.01,
        price=100.0,
        current_price=120.0,
    ) == pytest.approx(2.4)
    with pytest.raises(ValueError, match="current_price"):
        swap_bps_per_rollover(
            "INTEREST_CURRENT", -7.2, point=0.01, price=100.0
        )


def test_currency_symbol_swap_uses_base_currency_notional() -> None:
    assert swap_bps_per_rollover(
        "CURRENCY_SYMBOL",
        -25.0,
        point=0.01,
        price=20_000.0,
        contract_size=50.0,
        currency_base="HKD",
        currency_profit="HKD",
    ) == pytest.approx(0.25)
    with pytest.raises(ValueError, match="contract_size"):
        swap_bps_per_rollover(
            "CURRENCY_SYMBOL", -25.0, point=0.01, price=150.0
        )


def test_currency_symbol_cross_converts_base_at_rollover_price() -> None:
    assert swap_bps_per_rollover(
        "CURRENCY_SYMBOL",
        -25.0,
        point=0.00001,
        price=1.5,
        current_price=1.8,
        contract_size=100_000.0,
        currency_base="EUR",
        currency_profit="USD",
    ) == pytest.approx(3.0)


def test_axi_category_prefix_and_rollover_day_are_normalized_explicitly():
    assert normalize_mt5_category(r"ROW_STANDARD_FX\Majors") == "STANDARD_FX"
    assert normalize_mt5_category(r"CRYPTO\Crypto") == "CRYPTO"
    assert derive_rollover_multipliers(3, weekend_open=False) == (
        1.0,
        1.0,
        3.0,
        1.0,
        1.0,
        0.0,
        0.0,
    )
    assert derive_rollover_multipliers(0, weekend_open=True) == (
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        3.0,
    )


def test_swap_conversion_rejects_modes_without_a_lossless_bps_mapping():
    with pytest.raises(ValueError, match="unsupported swap mode"):
        swap_bps_per_rollover("CURRENCY_DEPOSIT", -1.0, point=0.01, price=100.0)


def test_point_swap_uses_each_trade_entry_price_not_a_current_price_snapshot():
    costs = CostModel(
        0.0,
        0.0,
        999.0,
        999.0,
        2,
        rollover_multipliers=(1.0, 1.0, 3.0, 1.0, 1.0, 0.0, 0.0),
        swap_mode="POINTS",
        swap_long_raw=-10.0,
        swap_short_raw=-10.0,
        point=0.01,
    )
    bars = [
        Bar(datetime(2026, 1, 5, tzinfo=UTC), 200, 202, 198, 200, 2, 1),
        Bar(datetime(2026, 1, 5, 1, tzinfo=UTC), 200, 201, 199, 200, 2, 0),
        Bar(datetime(2026, 1, 6, tzinfo=UTC), 200, 201, 199, 200, 2, 0),
    ]
    trade = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=8,
        costs=costs,
    )[0]
    assert trade.swap_cost_bps == pytest.approx(5.0)


def test_interest_current_swap_uses_each_rollover_days_last_close() -> None:
    costs = CostModel(
        0.0,
        0.0,
        0.0,
        0.0,
        4,
        rollover_multipliers=(1.0,) * 7,
        swap_mode="INTEREST_CURRENT",
        swap_long_raw=-3.6,
        swap_short_raw=-3.6,
        point=0.01,
    )
    bars = [
        Bar(datetime(2026, 1, 1, tzinfo=UTC), 100, 101, 99, 100, 100, 1),
        Bar(datetime(2026, 1, 1, 1, tzinfo=UTC), 100, 101, 99, 100, 100),
        Bar(datetime(2026, 1, 1, 23, tzinfo=UTC), 100, 121, 99, 120, 100),
        Bar(datetime(2026, 1, 2, 23, tzinfo=UTC), 120, 121, 79, 80, 100),
        Bar(datetime(2026, 1, 3, tzinfo=UTC), 80, 101, 79, 100, 100),
    ]

    trade = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=99,
        costs=costs,
    )[0]

    assert trade.swap_cost_bps == pytest.approx(2.0)


def test_currency_symbol_swap_is_applied_by_simulation() -> None:
    costs = CostModel(
        0.0,
        0.0,
        0.0,
        0.0,
        2,
        rollover_multipliers=(1.0,) * 7,
        swap_mode="CURRENCY_SYMBOL",
        swap_long_raw=-25.0,
        swap_short_raw=-25.0,
        point=0.01,
        contract_size=50.0,
        currency_base="HKD",
        currency_profit="HKD",
    )
    bars = [
        Bar(datetime(2026, 1, 1, tzinfo=UTC), 20_000, 20_100, 19_900, 20_000, 1_000, 1),
        Bar(datetime(2026, 1, 1, 1, tzinfo=UTC), 20_000, 20_100, 19_900, 20_000, 1_000),
        Bar(datetime(2026, 1, 2, tzinfo=UTC), 20_000, 20_100, 19_900, 20_000, 1_000),
    ]

    trade = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=99,
        costs=costs,
    )[0]

    assert trade.swap_cost_bps == pytest.approx(0.25)


def test_entry_bar_is_exposed_and_stop_wins_ambiguous_bar():
    bars = [
        _bar(0, signal=1),
        _bar(1, open_=100, high=103, low=98, close=102),
    ]
    trades = simulate(
        bars,
        sl_atr=1.0,
        tp_ladder=(1.0, 2.0, 3.0),
        time_stop_bars=8,
        costs=_zero_costs(),
    )
    assert len(trades) == 1
    assert trades[0].gross_bps == pytest.approx(-100.0)
    assert trades[0].initial_risk_bps == pytest.approx(100.0)


def test_close_during_bar_cannot_reopen_retroactively_at_that_bar_open():
    bars = [
        _bar(0, signal=1),
        _bar(1, signal=-1, open_=100, high=100.5, low=99.5, close=100),
        _bar(2, open_=100, high=103, low=98, close=102),
    ]
    trades = simulate(
        bars,
        sl_atr=1.0,
        tp_ladder=(1.0, 2.0, 3.0),
        time_stop_bars=8,
        costs=_zero_costs(),
    )
    assert len(trades) == 1
    assert trades[0].side == 1


def test_open_tail_position_is_marked_to_market_and_costs_are_recorded():
    costs = CostModel(2.0, 0.5, 1.0, 2.0, 2, commission_bps=0.25)
    bars = [
        _bar(0, signal=1),
        _bar(1, open_=100, high=100.5, low=99.5, close=100),
        _bar(2, open_=100, high=100.5, low=99.5, close=100.2),
    ]
    trades = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=8,
        costs=costs,
    )
    assert len(trades) == 1
    assert trades[0].execution_cost_bps == 2.75
    assert trades[0].net_bps == pytest.approx(17.25)


def test_broker_daily_rollover_multipliers_do_not_charge_closed_weekend_days():
    costs = CostModel(
        0.0,
        0.0,
        1.0,
        1.0,
        2,
        rollover_multipliers=(1.0, 1.0, 3.0, 1.0, 1.0, 0.0, 0.0),
    )
    bars = [
        Bar(datetime(2026, 1, 2, tzinfo=UTC), 100, 101, 99, 100, 1, 1),  # Friday
        Bar(datetime(2026, 1, 2, 1, tzinfo=UTC), 100, 100.5, 99.5, 100, 1, 0),
        Bar(datetime(2026, 1, 5, tzinfo=UTC), 100, 100.5, 99.5, 100, 1, 0),  # Monday
    ]
    trade = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=8,
        costs=costs,
    )[0]
    assert trade.swap_cost_bps == pytest.approx(1.0)


def test_triple_swap_is_charged_on_rollover_day_not_arrival_day():
    costs = CostModel(
        0.0,
        0.0,
        1.0,
        1.0,
        2,
        rollover_multipliers=(1.0, 1.0, 3.0, 1.0, 1.0, 0.0, 0.0),
    )
    bars = [
        Bar(datetime(2026, 1, 7, tzinfo=UTC), 100, 101, 99, 100, 1, 1),  # Wednesday
        Bar(datetime(2026, 1, 7, 1, tzinfo=UTC), 100, 100.5, 99.5, 100, 1, 0),
        Bar(datetime(2026, 1, 8, tzinfo=UTC), 100, 100.5, 99.5, 100, 1, 0),
    ]
    trade = simulate(
        bars,
        sl_atr=2.0,
        tp_ladder=(2.0, 3.0, 4.0),
        time_stop_bars=8,
        costs=costs,
    )[0]
    assert trade.swap_cost_bps == pytest.approx(3.0)


def test_daily_grid_and_fastest_validated_rule_are_deterministic():
    trade = simulate(
        [_bar(0, signal=1), _bar(1, open_=100, high=101, low=99.5, close=100)],
        sl_atr=2.0,
        tp_ladder=(1.0, 2.0, 3.0),
        time_stop_bars=1,
        costs=_zero_costs(),
    )[0]
    returns = aggregate_daily_returns(
        [trade], [date(2026, 1, 1), date(2026, 1, 2)], risk_fraction=0.07
    )
    assert returns == pytest.approx(
        ((trade.net_bps / trade.initial_risk_bps) * 0.07, 0.0)
    )
    reports = {
        "scalp": {"status": "OBSERVATION"},
        "intraday": {"status": "VALIDATED_FOR_FORWARD_PAPER"},
        "swing": {"status": "VALIDATED_FOR_FORWARD_PAPER"},
    }
    assert fastest_validated_style(reports) == "intraday"


def test_trade_economics_quantifies_frequency_cost_drag_and_break_even_spread():
    trades = (
        SimulatedTrade(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 1, tzinfo=UTC),
            1,
            100.0,
            10.0,
            2.0,
            1.0,
            7.0,
        ),
        SimulatedTrade(
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 2, 1, tzinfo=UTC),
            -1,
            100.0,
            -5.0,
            2.0,
            0.0,
            -7.0,
        ),
    )
    metrics = summarize_trade_economics(
        trades,
        trading_day_count=2,
        risk_fraction=0.07,
        account_balance=10_000.0,
        observed_spread_bps=1.5,
        spread_multiplier=1.25,
        commission_bps=0.0,
    )
    assert metrics["trades_per_day"] == pytest.approx(1.0)
    assert metrics["expectancy_net_bps"] == pytest.approx(0.0)
    assert metrics["expectancy_currency"] == pytest.approx(0.0)
    assert metrics["avg_win_net_bps"] == pytest.approx(7.0)
    assert metrics["avg_loss_net_bps"] == pytest.approx(-7.0)
    assert metrics["payoff_ratio"] == pytest.approx(1.0)
    assert metrics["total_cost_bps"] == pytest.approx(5.0)
    assert metrics["cost_pct_of_gross_profit"] == pytest.approx(50.0)
    assert metrics["break_even_spread_bps"] == pytest.approx(1.6)
    assert metrics["spread_safety_margin_bps"] == pytest.approx(0.1)
