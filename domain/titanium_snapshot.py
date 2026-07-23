"""Contrat de lecture TitaniumSnapshot v1 pour JARVIS, Hermes et les dashboards."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


DATA_STATUSES = {"LIVE", "STALE", "UNAVAILABLE"}
VALIDATION_STATUSES = {"research", "paper", "reviewed", "approved_paper", "blocked"}


@dataclass(frozen=True)
class StrategyInput:
    strategy_id: str
    source: str
    source_ts: datetime | str | None
    stale_after_seconds: int
    realized_pnl: float | None
    realized_pnl_unit: str
    winrate_pct: float | None
    trades: int | None
    equity: float | None
    equity_unit: str
    score: float | None
    score_max: float | None
    validation: Mapping[str, Any]
    score_source: str | None = None
    score_source_ts: datetime | str | None = None


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalize_score_16(score: float | None, score_max: float | None) -> float | None:
    try:
        value = float(score) if score is not None else math.nan
        maximum = float(score_max) if score_max is not None else math.nan
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or not math.isfinite(maximum) or maximum <= 0:
        return None
    return round(max(0.0, min(16.0, value / maximum * 16.0)), 2)


def _freshness(
    source_ts: datetime | str | None,
    stale_after_seconds: int,
    now: datetime,
) -> tuple[str, str | None, float | None]:
    parsed = _utc(source_ts)
    if parsed is None or stale_after_seconds <= 0:
        return "UNAVAILABLE", None, None
    age = (now - parsed).total_seconds()
    if age < 0:
        return "UNAVAILABLE", parsed.isoformat(), None
    status = "LIVE" if age <= stale_after_seconds else "STALE"
    return status, parsed.isoformat(), round(age, 3)


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _datum(
    value: float | int | None,
    *,
    unit: str,
    source: str,
    source_ts: datetime | str | None,
    stale_after_seconds: int,
    now: datetime,
    scale_max: int | None = None,
) -> dict[str, Any]:
    status, timestamp, age = _freshness(source_ts, stale_after_seconds, now)
    if not _valid_number(value):
        status = "UNAVAILABLE"
        value = None
    result: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "source": source,
        "source_ts": timestamp,
        "age_seconds": age,
        "stale_after_seconds": stale_after_seconds,
        "status": status,
    }
    if scale_max is not None:
        result["scale_max"] = scale_max
    return result


def _validation(value: Mapping[str, Any]) -> dict[str, Any]:
    status = value.get("status")
    if status not in VALIDATION_STATUSES:
        raise ValueError(f"unknown validation status: {status!r}")
    for key in ("version", "updated_at", "source"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"validation {key} is required")
    updated_at = _utc(value["updated_at"])
    if updated_at is None:
        raise ValueError("validation updated_at must be an ISO-8601 timestamp with timezone")
    return {
        "status": status,
        "version": value["version"],
        "updated_at": updated_at.isoformat(),
        "source": value["source"],
        "notes": str(value.get("notes", "")),
    }


def build_titanium_snapshot(
    strategies: Sequence[StrategyInput],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output: dict[str, Any] = {}
    statuses: list[str] = []
    for item in strategies:
        if item.strategy_id in output:
            raise ValueError(f"duplicate strategy_id: {item.strategy_id}")
        status, timestamp, age = _freshness(
            item.source_ts, item.stale_after_seconds, generated
        )
        statuses.append(status)
        score_source = item.score_source or item.source
        score_ts = item.score_source_ts if item.score_source_ts is not None else item.source_ts
        output[item.strategy_id] = {
            "status": status,
            "source": item.source,
            "source_ts": timestamp,
            "age_seconds": age,
            "stale_after_seconds": item.stale_after_seconds,
            "metrics": {
                "realized_pnl": _datum(
                    item.realized_pnl, unit=item.realized_pnl_unit,
                    source=item.source, source_ts=item.source_ts,
                    stale_after_seconds=item.stale_after_seconds, now=generated,
                ),
                "winrate_pct": _datum(
                    item.winrate_pct, unit="percent", source=item.source,
                    source_ts=item.source_ts,
                    stale_after_seconds=item.stale_after_seconds, now=generated,
                ),
                "trades": _datum(
                    item.trades, unit="count", source=item.source,
                    source_ts=item.source_ts,
                    stale_after_seconds=item.stale_after_seconds, now=generated,
                ),
                "equity": _datum(
                    item.equity, unit=item.equity_unit, source=item.source,
                    source_ts=item.source_ts,
                    stale_after_seconds=item.stale_after_seconds, now=generated,
                ),
                "score": _datum(
                    normalize_score_16(item.score, item.score_max), unit="points",
                    source=score_source, source_ts=score_ts,
                    stale_after_seconds=item.stale_after_seconds, now=generated,
                    scale_max=16,
                ),
            },
            "validation": _validation(item.validation),
        }
    overall = "LIVE"
    if "UNAVAILABLE" in statuses or not statuses:
        overall = "UNAVAILABLE"
    elif "STALE" in statuses:
        overall = "STALE"
    return {
        "schema": "TitaniumSnapshot",
        "schema_version": "1.0",
        "generated_at": generated.isoformat(),
        "paper_only": True,
        "status": overall,
        "strategies": output,
    }
