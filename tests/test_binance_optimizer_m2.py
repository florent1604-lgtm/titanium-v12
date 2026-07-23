from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

import tools.binance_optimizer_m2 as binance_m2
from tools.binance_optimizer_m2 import (
    DEFAULT_SYMBOLS,
    build_cost_context,
    calibrate_binance_asset,
    load_binance_frames,
    main,
)


UTC = timezone.utc


@pytest.mark.parametrize(
    ("mode", "per_side", "round_trip", "total_execution"),
    (
        ("taker", 10.0, 20.0, 22.25),
        ("maker", 7.5, 15.0, 17.25),
    ),
)
def test_cost_context_converts_binance_per_side_fee_to_round_trip(
    mode: str,
    per_side: float,
    round_trip: float,
    total_execution: float,
) -> None:
    costs, snapshot = build_cost_context(
        mode,
        spread_multiplier=1.25,
        reference_balance=10_000.0,
    )

    assert snapshot["commission_bps_per_side"] == pytest.approx(per_side)
    assert snapshot["commission_bps"] == pytest.approx(round_trip)
    assert costs.commission_bps == pytest.approx(round_trip)
    assert (
        costs.spread_bps + costs.slippage_bps + costs.commission_bps
    ) == pytest.approx(total_execution)
    assert costs.swap_long_bps_per_rollover == 0.0
    assert costs.swap_short_bps_per_rollover == 0.0
    assert snapshot["funding_bps"] == 0.0
    assert snapshot["funding_assumption"] == "binance_spot_no_funding"


def test_cost_context_rejects_an_unknown_execution_mode() -> None:
    with pytest.raises(ValueError, match="execution mode"):
        build_cost_context(
            "vip-secret-tier",
            spread_multiplier=1.25,
            reference_balance=10_000.0,
        )


def _ohlcv_frame(tf_minutes: int, now: datetime, periods: int = 900) -> pd.DataFrame:
    end = pd.Timestamp(now - timedelta(minutes=tf_minutes / 2))
    index = pd.date_range(end=end, periods=periods, freq=f"{tf_minutes}min", tz="UTC")
    base = pd.Series(
        [100.0 + (index_value % 20) - 10.0 for index_value in range(periods)],
        index=index,
        dtype=float,
    )
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base + 0.5,
            "v": 1_000.0,
        },
        index=index,
    )


def test_load_frames_removes_open_bars_and_reuses_the_isolated_cache(tmp_path) -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    minutes = {"M15": 15, "H1": 60, "H4": 240}
    calls: list[str] = []

    def fetcher(symbol: str, tf: str, years: float) -> pd.DataFrame:
        assert symbol == "BTCUSDT"
        assert years == 4.0
        calls.append(tf)
        return _ohlcv_frame(minutes[tf], now)

    frames = load_binance_frames(
        "BTCUSDT",
        4.0,
        tmp_path,
        fetcher=fetcher,
        now=now,
    )

    assert calls == ["M15", "H1", "H4"]
    assert set(frames) == {"scalp", "intraday", "swing"}
    for style, frame in frames.items():
        tf = {"scalp": "M15", "intraday": "H1", "swing": "H4"}[style]
        assert frame.index[-1] + pd.Timedelta(minutes=minutes[tf]) <= now
        assert len(frame) >= 600

    def forbidden_fetcher(symbol: str, tf: str, years: float) -> pd.DataFrame:
        raise AssertionError("cache was not reused")

    cached = load_binance_frames(
        "BTCUSDT",
        4.0,
        tmp_path,
        fetcher=forbidden_fetcher,
        now=now,
    )
    assert {style: len(frame) for style, frame in cached.items()} == {
        style: len(frame) for style, frame in frames.items()
    }


def test_load_frames_fails_closed_on_insufficient_closed_history(tmp_path) -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    def short_fetcher(symbol: str, tf: str, years: float) -> pd.DataFrame:
        return _ohlcv_frame({"M15": 15, "H1": 60, "H4": 240}[tf], now, periods=300)

    with pytest.raises(RuntimeError, match="insufficient closed M15 bars"):
        load_binance_frames(
            "BTCUSDT",
            4.0,
            tmp_path,
            fetcher=short_fetcher,
            now=now,
        )


def _prepared_frames(start: str, periods: int) -> dict[str, pd.DataFrame]:
    result = {}
    for style in ("scalp", "intraday", "swing"):
        index = pd.date_range(start=start, periods=periods, freq="1D", tz="UTC")
        price = pd.Series(
            [100.0 + (item % 20) for item in range(periods)],
            index=index,
            dtype=float,
        )
        result[style] = pd.DataFrame(
            {
                "open": price,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price + 0.5,
                "atr": 2.0,
            },
            index=index,
        )
    return result


def test_calibrate_binance_asset_uses_all_m2_styles_and_fastest_proposal(
    monkeypatch,
) -> None:
    frames = _prepared_frames("2023-01-01", 1_100)
    calls: list[tuple[str, float, str]] = []

    def fake_calibrate_style(
        symbol,
        style,
        frame,
        window,
        costs,
        snapshot,
        bootstrap_replications,
        risk_fraction,
    ):
        calls.append((style, risk_fraction, snapshot["execution_mode"]))
        status = "VALIDATED_FOR_FORWARD_PAPER" if style == "intraday" else "OBSERVATION"
        return {
            "status": status,
            "selected_config": {"name": f"{style}.fixed"},
            "pbo": 0.25,
            "deflated_sharpe": 0.6,
            "final_intervals": {},
            "final_trades_per_year": 80.0,
            "final_trade_metrics_bps": {"trades": 32},
            "candidates": [],
        }

    monkeypatch.setattr(binance_m2, "_calibrate_style", fake_calibrate_style)

    result = calibrate_binance_asset(
        "BTCUSDT",
        "maker",
        frames,
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        spread_multiplier=1.25,
        bootstrap_replications=2_000,
        risk_pct=7.0,
        reference_balance=10_000.0,
    )

    assert calls == [
        ("scalp", 0.07, "MAKER"),
        ("intraday", 0.07, "MAKER"),
        ("swing", 0.07, "MAKER"),
    ]
    assert result["status"] == "CALIBRATED"
    assert result["source"] == "BINANCE_SPOT"
    assert result["scenario"] == "MAKER"
    assert result["proposed"]["style"] == "intraday"
    assert result["proposed"]["m2_status"] == "VALIDATED_FOR_FORWARD_PAPER"
    assert "demo_login" not in result


def test_calibrate_binance_asset_fails_closed_below_two_common_years(monkeypatch) -> None:
    frames = _prepared_frames("2025-01-01", 400)

    def forbidden(*args, **kwargs):
        raise AssertionError("M2 calibration must not run on a short window")

    monkeypatch.setattr(binance_m2, "_calibrate_style", forbidden)
    result = calibrate_binance_asset(
        "BTCUSDT",
        "taker",
        frames,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 7, 16, tzinfo=UTC),
        spread_multiplier=1.25,
        bootstrap_replications=2_000,
        risk_pct=7.0,
        reference_balance=10_000.0,
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert "shorter than 730 days" in result["reason"]


def test_default_universe_is_the_ten_preregistered_binance_symbols() -> None:
    assert DEFAULT_SYMBOLS == (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "BNBUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "LTCUSDT",
    )


def test_main_writes_isolated_taker_and_maker_checkpoints(tmp_path, monkeypatch) -> None:
    frame_calls: list[str] = []
    calibration_calls: list[tuple[str, str]] = []

    def fake_load(symbol, years, cache_root, **kwargs):
        frame_calls.append(symbol)
        return _prepared_frames("2023-01-01", 1_100)

    def fake_calibrate(symbol, scenario, frames, requested_start, requested_end, **kwargs):
        calibration_calls.append((symbol, scenario))
        proposal = {"style": "scalp"} if scenario == "maker" else None
        return {
            "symbol": symbol,
            "source": "BINANCE_SPOT",
            "scenario": scenario.upper(),
            "status": "CALIBRATED",
            "proposed": proposal,
        }

    monkeypatch.setattr(binance_m2, "load_binance_frames", fake_load)
    monkeypatch.setattr(binance_m2, "calibrate_binance_asset", fake_calibrate)

    assert main(
        [
            "--symbols",
            "BTCUSDT",
            "--scenarios",
            "taker,maker",
            "--bootstrap-replications",
            "100",
            "--output-dir",
            str(tmp_path),
        ]
    ) == 0

    assert frame_calls == ["BTCUSDT"]
    assert calibration_calls == [("BTCUSDT", "taker"), ("BTCUSDT", "maker")]
    assert (tmp_path / "assets" / "BTCUSDT.taker.json").is_file()
    assert (tmp_path / "assets" / "BTCUSDT.maker.json").is_file()
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] == 2
    assert summary["results"]["BTCUSDT"]["maker"]["scenario"] == "MAKER"
    assert "demo_login" not in summary
    proposal = json.loads(
        (tmp_path / "asset_configs.proposal.json").read_text(encoding="utf-8")
    )
    assert proposal["assets"] == {"BTCUSDT:MAKER": {"style": "scalp"}}


def test_main_rejects_an_unknown_scenario_before_loading_data(tmp_path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("data must not load for an invalid scenario")

    monkeypatch.setattr(binance_m2, "load_binance_frames", forbidden)
    with pytest.raises(ValueError, match="execution mode"):
        main(
            [
                "--symbols",
                "BTCUSDT",
                "--scenarios",
                "taker,vip",
                "--output-dir",
                str(tmp_path),
            ]
        )


def test_script_reports_cli_validation_errors_without_a_traceback() -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "binance_optimizer_m2.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--years", "1"],
        cwd=script.parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "ERROR: --years must be at least 2" in completed.stderr
    assert "Traceback" not in completed.stderr
