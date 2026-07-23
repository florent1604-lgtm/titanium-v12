from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain.titanium_snapshot import (
    StrategyInput,
    build_titanium_snapshot,
    normalize_score_16,
)


NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)


def _strategy(source_ts: datetime | str | None, **overrides) -> StrategyInput:
    values = {
        "strategy_id": "crypto",
        "source": "execution.paper_trading.PaperEngine",
        "source_ts": source_ts,
        "stale_after_seconds": 60,
        "realized_pnl": 12.5,
        "realized_pnl_unit": "USDT",
        "winrate_pct": 55.0,
        "trades": 20,
        "equity": 1012.5,
        "equity_unit": "USDT",
        "score": 8,
        "score_max": 11,
        "validation": {
            "status": "paper",
            "version": "crypto-paper-v1",
            "updated_at": "2026-07-11T10:00:00+00:00",
            "source": "validation/strategy_status.json",
        },
    }
    values.update(overrides)
    return StrategyInput(**values)


def test_score_is_explicitly_normalized_to_sixteen() -> None:
    assert normalize_score_16(8, 11) == pytest.approx(11.64)
    assert normalize_score_16(99, 11) == 16.0
    assert normalize_score_16(None, 11) is None


def test_snapshot_marks_live_stale_and_unavailable_fail_closed() -> None:
    snapshot = build_titanium_snapshot(
        [
            _strategy(NOW - timedelta(seconds=10), strategy_id="live"),
            _strategy(NOW - timedelta(seconds=61), strategy_id="stale"),
            _strategy(None, strategy_id="missing"),
        ],
        now=NOW,
    )

    assert snapshot["strategies"]["live"]["status"] == "LIVE"
    assert snapshot["strategies"]["stale"]["status"] == "STALE"
    assert snapshot["strategies"]["missing"]["status"] == "UNAVAILABLE"
    assert snapshot["status"] == "UNAVAILABLE"


def test_each_metric_carries_provenance_age_and_unit() -> None:
    snapshot = build_titanium_snapshot([_strategy(NOW)], now=NOW)
    strategy = snapshot["strategies"]["crypto"]

    for name in ("realized_pnl", "winrate_pct", "trades", "equity", "score"):
        datum = strategy["metrics"][name]
        assert datum["source"] == "execution.paper_trading.PaperEngine"
        assert datum["source_ts"] == NOW.isoformat()
        assert datum["age_seconds"] == 0.0
        assert datum["stale_after_seconds"] == 60
        assert datum["status"] == "LIVE"
    assert strategy["metrics"]["realized_pnl"]["unit"] == "USDT"
    assert strategy["metrics"]["score"]["scale_max"] == 16


def test_missing_metric_value_is_unavailable_even_when_source_is_fresh() -> None:
    snapshot = build_titanium_snapshot(
        [_strategy(NOW, winrate_pct=None, score=None)], now=NOW
    )
    metrics = snapshot["strategies"]["crypto"]["metrics"]
    assert metrics["winrate_pct"]["status"] == "UNAVAILABLE"
    assert metrics["score"]["status"] == "UNAVAILABLE"


def test_unknown_validation_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="validation status"):
        build_titanium_snapshot(
            [_strategy(NOW, validation={"status": "live-approved"})], now=NOW
        )


def test_future_source_timestamp_is_unavailable_not_live() -> None:
    snapshot = build_titanium_snapshot(
        [_strategy(NOW + timedelta(seconds=1))], now=NOW
    )
    strategy = snapshot["strategies"]["crypto"]
    assert strategy["status"] == "UNAVAILABLE"
    assert strategy["age_seconds"] is None
    assert strategy["source_ts"] == (NOW + timedelta(seconds=1)).isoformat()


def test_duplicate_strategy_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate strategy_id"):
        build_titanium_snapshot([_strategy(NOW), _strategy(NOW)], now=NOW)


def test_validation_updated_at_requires_a_timezone() -> None:
    validation = {
        "status": "paper",
        "version": "crypto-paper-v1",
        "updated_at": "2026-07-11T10:00:00",
        "source": "validation/strategy_status.json",
    }
    with pytest.raises(ValueError, match="updated_at"):
        build_titanium_snapshot([_strategy(NOW, validation=validation)], now=NOW)


def test_versioned_contract_contains_secret_free_example() -> None:
    contract = json.loads(
        Path("docs/contracts/titanium_snapshot_v1.json").read_text(encoding="utf-8")
    )
    example = contract["examples"][0]
    assert contract["title"] == "TitaniumSnapshot v1"
    assert example["schema_version"] == "1.0"
    assert example["paper_only"] is True
    serialized = json.dumps(example).lower()
    assert all(secret not in serialized for secret in ("password", "token", "api_key", "secret"))


def test_snapshot_has_both_read_only_routes() -> None:
    routes = Path("api/snapshot_routes.py").read_text(encoding="utf-8")
    server = Path("api/api_server.py").read_text(encoding="utf-8")
    assert '@router.get("/v1")' in routes
    assert '@canonical_router.get("/api/v1/snapshot")' in routes
    assert "snapshot_canonical_router" in server
    assert ".post(" not in routes
