"""Three-segment validation with block bootstrap and multiplicity diagnostics.

This module does not fetch data or mutate the repository. A caller supplies an
evaluator(candidate, segment) function, so the exact same strategy/cost model
can be used by paper and backtest adapters.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from statistics import NormalDist
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence, Tuple


class ValidationStatus(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OBSERVATION = "OBSERVATION"
    VALIDATED_FOR_FORWARD_PAPER = "VALIDATED_FOR_FORWARD_PAPER"


@dataclass(frozen=True)
class Segment:
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("segment start must be before end")


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _hash(value: Any) -> str:
    raw = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ValidationPlan:
    dev: Segment
    selection: Segment
    final: Segment
    experiment: Mapping[str, Any]
    block_length: int = 5
    bootstrap_replications: int = 10_000
    bootstrap_seed: int = 20260710
    preregistration_hash: str = field(init=False)

    def __post_init__(self) -> None:
        segments = (self.dev, self.selection, self.final)
        if [segment.name for segment in segments] != ["dev", "selection", "final"]:
            raise ValueError("segments must be ordered dev, selection, final")
        for left, right in zip(segments, segments[1:]):
            if left.end > right.start:
                raise ValueError("validation segments must not overlap")
        if self.block_length < 1:
            raise ValueError("block_length must be positive")
        if self.bootstrap_replications < 100:
            raise ValueError("bootstrap_replications must be at least 100")
        payload = {
            "dev": asdict(self.dev),
            "selection": asdict(self.selection),
            "final": asdict(self.final),
            "experiment": self.experiment,
            "block_length": self.block_length,
            "bootstrap_replications": self.bootstrap_replications,
            "bootstrap_seed": self.bootstrap_seed,
        }
        object.__setattr__(self, "preregistration_hash", _hash(payload))

    def verify(self) -> bool:
        payload = {
            "dev": asdict(self.dev),
            "selection": asdict(self.selection),
            "final": asdict(self.final),
            "experiment": self.experiment,
            "block_length": self.block_length,
            "bootstrap_replications": self.bootstrap_replications,
            "bootstrap_seed": self.bootstrap_seed,
        }
        return self.preregistration_hash == _hash(payload)


def compute_metrics(
    returns: Sequence[float],
    *,
    trade_count: int | None = None,
    periods_per_year: float = 252.0,
) -> Dict[str, float]:
    values = []
    for item in returns:
        if isinstance(item, bool):
            raise ValueError("returns must contain finite numbers")
        value = float(item)
        if not math.isfinite(value):
            raise ValueError("returns must contain finite numbers")
        values.append(value)
    if trade_count is None:
        trade_count = len(values)
    if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 0:
        raise ValueError("trade_count must be a non-negative integer")
    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, (int, float))
        or not math.isfinite(float(periods_per_year))
        or periods_per_year <= 0
    ):
        raise ValueError("periods_per_year must be finite and positive")
    if not values:
        return {
            "trades": float(trade_count),
            "observations": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
    wins = [item for item in values if item > 0]
    losses = [item for item in values if item <= 0]
    equity = 1.0
    peak = equity
    max_dd = 0.0
    curve = []
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        curve.append(equity)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    stdev = math.sqrt(variance)
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return {
        "trades": float(trade_count),
        "observations": float(len(values)),
        "expectancy": mean,
        "profit_factor": profit_factor,
        "winrate": len(wins) / len(values),
        "max_drawdown": max_dd,
        "sharpe": mean / stdev * math.sqrt(periods_per_year) if stdev > 0 else 0.0,
    }


def block_bootstrap(
    values: Sequence[float],
    block_length: int,
    replications: int,
    seed: int,
    *,
    stationary: bool = False,
) -> Tuple[Tuple[float, ...], ...]:
    """Return deterministic moving or stationary block resamples."""
    source = tuple(float(item) for item in values)
    if not source or block_length < 1 or replications < 1:
        return ()
    rng = random.Random(seed)
    result = []
    n = len(source)
    for _ in range(replications):
        sample = []
        if stationary:
            index = rng.randrange(n)
            while len(sample) < n:
                sample.append(source[index])
                if rng.random() < 1.0 / block_length:
                    index = rng.randrange(n)
                else:
                    index = (index + 1) % n
        else:
            while len(sample) < n:
                start = rng.randrange(n)
                sample.extend(source[start:start + block_length])
        result.append(tuple(sample[:n]))
    return tuple(result)


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_intervals(
    values: Sequence[float],
    block_length: int,
    replications: int,
    seed: int,
) -> Dict[str, Tuple[float, float]]:
    samples = block_bootstrap(values, block_length, replications, seed)
    if not samples:
        return {}
    metrics = {key: [] for key in compute_metrics(values)}
    for sample in samples:
        for key, metric in compute_metrics(sample).items():
            metrics[key].append(float(metric))
    return {
        key: (_quantile(items, 0.025), _quantile(items, 0.975))
        for key, items in metrics.items()
    }


def estimate_pbo(
    returns_by_candidate: Mapping[str, Sequence[float]],
    *,
    n_blocks: int = 6,
) -> float | None:
    """Approximate CSCV PBO over all candidate returns.

    The value is the share of chronological half-partitions for which the
    candidate selected on the first half ranks at or below the median on the
    complementary half. It is deliberately reported as a diagnostic, not a
    validation gate by itself.
    """
    names = list(returns_by_candidate)
    if len(names) < 2:
        return None
    lengths = {len(returns_by_candidate[name]) for name in names}
    if len(lengths) != 1:
        raise ValueError("all candidates must have the same number of returns")
    total = next(iter(lengths))
    n_blocks = min(n_blocks, total)
    if n_blocks < 2:
        return None
    if n_blocks % 2:
        n_blocks -= 1
    block_size = total // n_blocks
    if block_size < 1:
        return None
    blocks = [
        list(range(index * block_size, (index + 1) * block_size))
        for index in range(n_blocks)
    ]
    half = n_blocks // 2
    failures = 0
    partitions = 0
    for is_blocks in itertools.combinations(range(n_blocks), half):
        is_set = set(is_blocks)
        oos_blocks = [index for index in range(n_blocks) if index not in is_set]
        is_indices = [item for index in is_blocks for item in blocks[index]]
        oos_indices = [item for index in oos_blocks for item in blocks[index]]
        is_means = {
            name: sum(returns_by_candidate[name][index] for index in is_indices) / len(is_indices)
            for name in names
        }
        selected = max(names, key=lambda name: is_means[name])
        oos_means = {
            name: sum(returns_by_candidate[name][index] for index in oos_indices)
            / len(oos_indices)
            for name in names
        }
        selected_oos = oos_means[selected]
        rank = sum(1 for value in oos_means.values() if value <= selected_oos) / len(oos_means)
        failures += int(rank <= 0.5)
        partitions += 1
    return failures / partitions if partitions else None


def deflated_sharpe_ratio(
    values: Sequence[float],
    trials: int,
    *,
    trial_sharpes: Sequence[float] | None = None,
) -> float:
    """Return the Bailey/López de Prado DSR probability.

    Sharpe ratios are per-observation (not annualized).  ``trial_sharpes``
    supplies the pre-final cross-trial dispersion used for the multiplicity
    threshold.  Without it, the null standard error is used conservatively.
    """
    returns = [float(item) for item in values]
    if any(not math.isfinite(item) for item in returns):
        raise ValueError("returns must contain finite numbers")
    if len(returns) < 3 or trials < 1:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / len(returns)
    stdev = math.sqrt(variance)
    if stdev <= max(1e-15, abs(mean) * 1e-12):
        return 0.0
    sharpe = mean / stdev
    third = sum((item - mean) ** 3 for item in returns) / len(returns)
    fourth = sum((item - mean) ** 4 for item in returns) / len(returns)
    skew = third / (stdev ** 3)
    kurtosis = fourth / (stdev ** 4)
    normal = NormalDist()
    if trials == 1:
        expected_max = 0.0
    else:
        if trial_sharpes is not None:
            trial_values = [float(item) for item in trial_sharpes]
            if not trial_values or len(trial_values) > trials or any(
                not math.isfinite(item) for item in trial_values
            ):
                raise ValueError(
                    "trial_sharpes must contain finite values for no more than all trials"
                )
            trial_mean = sum(trial_values) / len(trial_values)
            trial_variance = sum(
                (item - trial_mean) ** 2 for item in trial_values
            ) / len(trial_values)
            trial_sigma = math.sqrt(trial_variance)
        else:
            trial_sigma = 1.0 / math.sqrt(len(returns) - 1)
        euler_gamma = 0.5772156649015329
        expected_max = trial_sigma * (
            (1.0 - euler_gamma) * normal.inv_cdf(1.0 - 1.0 / trials)
            + euler_gamma * normal.inv_cdf(1.0 - 1.0 / (trials * math.e))
        )
    denominator = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe ** 2
    denominator = math.sqrt(max(denominator, 1e-9))
    z = (sharpe - expected_max) * math.sqrt(max(len(returns) - 1, 1)) / denominator
    return normal.cdf(z)


@dataclass(frozen=True)
class ValidationGate:
    min_trades: int = 30
    min_profit_factor: float = 1.20
    min_expectancy: float = 0.0
    max_drawdown: float = 0.20
    min_deflated_sharpe: float = 0.50
    max_pbo: float = 0.50

    def evaluate(
        self,
        final_metrics: Mapping[str, float],
        *,
        final_ran: bool,
        expectancy_lower: float | None,
        pbo: float | None,
        deflated_sharpe: float | None,
        evidence_ok: bool = True,
    ) -> ValidationStatus:
        if not final_ran:
            return ValidationStatus.OBSERVATION
        if not evidence_ok or int(final_metrics.get("trades", 0)) < self.min_trades:
            return ValidationStatus.INSUFFICIENT_EVIDENCE
        if (
            final_metrics.get("profit_factor", 0.0) < self.min_profit_factor
            or final_metrics.get("expectancy", 0.0) <= self.min_expectancy
            or (expectancy_lower is not None and expectancy_lower <= self.min_expectancy)
            or final_metrics.get("max_drawdown", 1.0) > self.max_drawdown
            or (pbo is not None and pbo > self.max_pbo)
            or (deflated_sharpe is not None and deflated_sharpe < self.min_deflated_sharpe)
        ):
            return ValidationStatus.OBSERVATION
        return ValidationStatus.VALIDATED_FOR_FORWARD_PAPER


@dataclass(frozen=True)
class CandidateResult:
    name: str
    dev: Dict[str, float]
    selection: Dict[str, float]
    final: Dict[str, float]


@dataclass(frozen=True)
class ValidationReport:
    status: ValidationStatus
    selected_candidate: str | None
    candidates: Tuple[CandidateResult, ...]
    final_intervals: Dict[str, Tuple[float, float]]
    pbo: float | None
    deflated_sharpe: float | None
    preregistration_hash: str
    notes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "selected_candidate": self.selected_candidate,
            "candidates": [asdict(item) for item in self.candidates],
            "final_intervals": self.final_intervals,
            "pbo": self.pbo,
            "deflated_sharpe": self.deflated_sharpe,
            "preregistration_hash": self.preregistration_hash,
            "notes": list(self.notes),
        }


def _returns(result: Any) -> Tuple[float, ...]:
    if isinstance(result, Mapping):
        result = result.get("returns", ())
    values = tuple(float(item) for item in result)
    if any(not math.isfinite(item) for item in values):
        raise ValueError("returns must contain finite numbers")
    return values


@dataclass(frozen=True)
class _Evaluation:
    returns: Tuple[float, ...]
    trade_returns: Tuple[float, ...]
    trade_count: int
    periods_per_year: float


def _evaluation(result: Any) -> _Evaluation:
    returns = _returns(result)
    if not isinstance(result, Mapping):
        return _Evaluation(returns, returns, len(returns), 252.0)
    trade_returns = tuple(float(item) for item in result.get("trade_returns", returns))
    if any(not math.isfinite(item) for item in trade_returns):
        raise ValueError("trade_returns must contain finite numbers")
    trade_count = result.get("trade_count", len(trade_returns))
    if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 0:
        raise ValueError("trade_count must be a non-negative integer")
    if trade_count != len(trade_returns):
        raise ValueError("trade_count must equal the number of trade_returns")
    periods_per_year = result.get("periods_per_year", 252.0)
    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, (int, float))
        or not math.isfinite(float(periods_per_year))
        or periods_per_year <= 0
    ):
        raise ValueError("periods_per_year must be finite and positive")
    return _Evaluation(returns, trade_returns, trade_count, float(periods_per_year))


def _evaluation_metrics(evaluation: _Evaluation) -> Dict[str, float]:
    trade_metrics = compute_metrics(
        evaluation.trade_returns,
        trade_count=evaluation.trade_count,
        periods_per_year=1.0,
    )
    observation_metrics = compute_metrics(
        evaluation.returns, periods_per_year=evaluation.periods_per_year
    )
    trade_metrics["observations"] = float(len(evaluation.returns))
    trade_metrics["max_drawdown"] = observation_metrics["max_drawdown"]
    trade_metrics["sharpe"] = observation_metrics["sharpe"]
    return trade_metrics


def _period_sharpe(values: Sequence[float]) -> float:
    source = tuple(float(item) for item in values)
    if len(source) < 2:
        return 0.0
    mean = sum(source) / len(source)
    variance = sum((item - mean) ** 2 for item in source) / len(source)
    return mean / math.sqrt(variance) if variance > 0 else (1.0 if mean > 0 else 0.0)


def _candidate_gate(plan: ValidationPlan) -> Dict[str, float]:
    raw = plan.experiment.get("candidate_gate", {})
    if not isinstance(raw, Mapping):
        raise ValueError("candidate_gate must be an object")
    defaults: Dict[str, float] = {
        "min_dev_trades": 1.0,
        "min_selection_trades": 1.0,
        "min_dev_expectancy": -math.inf,
        "min_selection_expectancy": -math.inf,
        "min_dev_profit_factor": -math.inf,
        "min_selection_profit_factor": -math.inf,
    }
    unknown = set(raw) - set(defaults)
    if unknown:
        raise ValueError(f"unknown candidate_gate fields: {sorted(unknown)}")
    result = dict(defaults)
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"candidate_gate.{key} must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"candidate_gate.{key} must be finite")
        if key.endswith("_trades") and (number < 0 or not number.is_integer()):
            raise ValueError(f"candidate_gate.{key} must be a non-negative integer")
        result[key] = number
    return result


def run_validation(
    candidates: Mapping[str, Any],
    plan: ValidationPlan,
    evaluator: Callable[[Any, Segment], Sequence[float] | Mapping[str, Any]],
    gate: ValidationGate | None = None,
) -> ValidationReport:
    """Run dev and selection for all candidates, final once for the winner."""
    if not plan.verify():
        raise ValueError("validation plan preregistration hash mismatch")
    gate = gate or ValidationGate()
    dev_results: Dict[str, _Evaluation] = {}
    selection_results: Dict[str, _Evaluation] = {}
    candidate_list = list(candidates)
    multiplicity_trials = plan.experiment.get("multiplicity_trials", len(candidate_list))
    if (
        isinstance(multiplicity_trials, bool)
        or not isinstance(multiplicity_trials, int)
        or multiplicity_trials < len(candidate_list)
    ):
        raise ValueError("multiplicity_trials must cover every evaluated candidate")
    for name in candidate_list:
        candidate = candidates[name]
        dev_results[name] = _evaluation(evaluator(candidate, plan.dev))
        selection_results[name] = _evaluation(evaluator(candidate, plan.selection))
    candidate_gate = _candidate_gate(plan)
    viable = [
        name
        for name in candidate_list
        if selection_results[name].returns
        and dev_results[name].trade_count >= candidate_gate["min_dev_trades"]
        and selection_results[name].trade_count >= candidate_gate["min_selection_trades"]
        and _evaluation_metrics(dev_results[name])["expectancy"]
        > candidate_gate["min_dev_expectancy"]
        and _evaluation_metrics(selection_results[name])["expectancy"]
        > candidate_gate["min_selection_expectancy"]
        and _evaluation_metrics(dev_results[name])["profit_factor"]
        > candidate_gate["min_dev_profit_factor"]
        and _evaluation_metrics(selection_results[name])["profit_factor"]
        > candidate_gate["min_selection_profit_factor"]
    ]
    if not viable:
        empty = tuple(
            CandidateResult(
                name,
                _evaluation_metrics(dev_results[name]),
                _evaluation_metrics(selection_results[name]),
                {},
            )
            for name in candidate_list
        )
        return ValidationReport(
            ValidationStatus.INSUFFICIENT_EVIDENCE,
            None,
            empty,
            {},
            None,
            None,
            plan.preregistration_hash,
            ("no candidate produced selection returns",),
        )
    selected = max(
        viable,
        key=lambda name: _evaluation_metrics(selection_results[name])["expectancy"],
    )
    final_result = _evaluation(evaluator(candidates[selected], plan.final))
    final_returns = final_result.returns
    final_metrics = _evaluation_metrics(final_result)
    intervals = bootstrap_intervals(
        final_returns,
        plan.block_length,
        plan.bootstrap_replications,
        plan.bootstrap_seed,
    )
    # CSCV/PBO must retain every preregistered trial with selection evidence.
    # Filtering to the viability winners would discard losing trials after the
    # fact and mechanically understate the probability of overfitting.
    pbo_inputs = {
        name: selection_results[name].returns
        for name in candidate_list
        if selection_results[name].returns
    }
    pbo = estimate_pbo(pbo_inputs)
    selection_sharpes = [
        _period_sharpe(selection_results[name].returns) for name in candidate_list
    ]
    dsr = (
        deflated_sharpe_ratio(
            final_returns,
            multiplicity_trials,
            trial_sharpes=selection_sharpes,
        )
        if final_returns
        else None
    )
    status = gate.evaluate(
        final_metrics,
        final_ran=True,
        expectancy_lower=intervals.get("expectancy", (None, None))[0],
        pbo=pbo,
        deflated_sharpe=dsr,
    )
    results = tuple(
        CandidateResult(
            name,
            _evaluation_metrics(dev_results[name]),
            _evaluation_metrics(selection_results[name]),
            final_metrics if name == selected else {},
        )
        for name in candidate_list
    )
    return ValidationReport(
        status,
        selected,
        results,
        intervals,
        pbo,
        dsr,
        plan.preregistration_hash,
        ("final segment evaluated once for selected candidate only",),
    )
