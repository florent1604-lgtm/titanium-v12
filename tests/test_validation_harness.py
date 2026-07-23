from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

import pytest
import validation.harness as harness_module

from validation.harness import (
    Segment,
    ValidationGate,
    ValidationPlan,
    ValidationStatus,
    block_bootstrap,
    compute_metrics,
    deflated_sharpe_ratio,
    estimate_pbo,
    run_validation,
)


def _plan():
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return ValidationPlan(
        dev=Segment("dev", base, base + timedelta(days=10)),
        selection=Segment("selection", base + timedelta(days=10), base + timedelta(days=20)),
        final=Segment("final", base + timedelta(days=20), base + timedelta(days=30)),
        experiment={"universe": ["A", "B"], "thresholds": {"min_trades": 30}},
        block_length=3,
        bootstrap_replications=200,
        bootstrap_seed=7,
    )


def test_segments_are_strictly_ordered_and_bootstrap_is_reproducible():
    plan = _plan()
    assert plan.verify()
    first = block_bootstrap([0.1, -0.1, 0.2, 0.0], 2, 5, 11)
    second = block_bootstrap([0.1, -0.1, 0.2, 0.0], 2, 5, 11)
    assert first == second
    assert all(len(sample) == 4 for sample in first)


def test_final_segment_is_evaluated_only_for_selected_candidate():
    plan = _plan()
    calls = []
    returns = {
        "A": [0.02] * 40,
        "B": [0.01] * 40,
    }

    def evaluator(candidate, segment):
        calls.append((candidate, segment.name))
        return returns[candidate]

    report = run_validation(
        {"A": "A", "B": "B"},
        plan,
        evaluator,
        ValidationGate(min_trades=30, min_deflated_sharpe=0.0),
    )
    assert report.selected_candidate == "A"
    assert ("A", "final") in calls
    assert ("B", "final") not in calls
    assert report.status in {
        ValidationStatus.OBSERVATION,
        ValidationStatus.VALIDATED_FOR_FORWARD_PAPER,
    }


def test_gate_rejects_insufficient_final_evidence():
    status = ValidationGate(min_trades=30).evaluate(
        {"trades": 12, "expectancy": 0.1, "profit_factor": 2.0, "max_drawdown": 0.01},
        final_ran=True,
        expectancy_lower=0.01,
        pbo=0.0,
        deflated_sharpe=1.0,
    )
    assert status is ValidationStatus.INSUFFICIENT_EVIDENCE


def test_reported_sharpe_is_annualized_not_a_sample_length_t_statistic():
    values = [0.01, -0.005, 0.02]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    expected = mean / math.sqrt(variance) * math.sqrt(365.0)
    assert compute_metrics(values, periods_per_year=365.0)["sharpe"] == pytest.approx(expected)


def test_pbo_ranks_candidate_oos_scores_not_pooled_observations():
    returns = {
        "A": [1, 0, 1, 0, 3, -3, -3, 3, 1, -1, 0, -1],
        "B": [1, 1, -3, -3, 3, 3, 0, 0, 0, 3, 1, 3],
        "C": [1, -3, -3, 0, 1, -3, -3, 0, 3, 1, 0, 1],
    }
    assert estimate_pbo(returns, n_blocks=6) == 0.25


def test_deflated_sharpe_matches_psr_formula_without_double_annualization():
    values = [0.010, -0.004, 0.008, 0.003, -0.002, 0.006, 0.001, -0.003]
    trial_sharpes = [0.08, 0.03, -0.02, 0.05]
    actual = deflated_sharpe_ratio(values, len(trial_sharpes), trial_sharpes=trial_sharpes)

    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    stdev = math.sqrt(variance)
    observed_sr = mean / stdev
    skew = sum((item - mean) ** 3 for item in values) / len(values) / stdev**3
    kurtosis = sum((item - mean) ** 4 for item in values) / len(values) / stdev**4
    trial_mean = sum(trial_sharpes) / len(trial_sharpes)
    trial_variance = sum((item - trial_mean) ** 2 for item in trial_sharpes) / len(trial_sharpes)
    euler_gamma = 0.5772156649015329
    normal = NormalDist()
    n_trials = len(trial_sharpes)
    expected_max = math.sqrt(trial_variance) * (
        (1 - euler_gamma) * normal.inv_cdf(1 - 1 / n_trials)
        + euler_gamma * normal.inv_cdf(1 - 1 / (n_trials * math.e))
    )
    denominator = math.sqrt(
        1 - skew * observed_sr + ((kurtosis - 1) / 4) * observed_sr**2
    )
    expected = normal.cdf(
        (observed_sr - expected_max) * math.sqrt(len(values) - 1) / denominator
    )
    assert actual == pytest.approx(expected)


def test_deflated_sharpe_does_not_validate_zero_variance_returns():
    assert deflated_sharpe_ratio(
        [0.01] * 40,
        108,
        trial_sharpes=[-0.02, 0.0, 0.02],
    ) == 0.0


def test_validation_gate_uses_real_trade_count_not_daily_observation_count():
    plan = _plan()

    def evaluator(candidate, segment):
        return {
            "returns": [0.002] * 40,
            "trade_returns": [0.016] * 5,
            "trade_count": 5,
        }

    report = run_validation(
        {"A": "A", "B": "B"},
        plan,
        evaluator,
        ValidationGate(min_trades=30, min_deflated_sharpe=0.0, max_pbo=1.0),
    )
    assert report.status is ValidationStatus.INSUFFICIENT_EVIDENCE
    selected = next(item for item in report.candidates if item.name == report.selected_candidate)
    assert selected.final["trades"] == 5
    assert selected.final["observations"] == 40


def test_preregistered_family_trial_count_drives_dsr_multiplicity(monkeypatch):
    base = _plan()
    plan = ValidationPlan(
        dev=base.dev,
        selection=base.selection,
        final=base.final,
        experiment={"multiplicity_trials": 108},
        block_length=base.block_length,
        bootstrap_replications=base.bootstrap_replications,
        bootstrap_seed=base.bootstrap_seed,
    )
    seen = []

    def fake_dsr(values, trials, *, trial_sharpes=None):
        seen.append((trials, len(trial_sharpes or ())))
        return 0.75

    monkeypatch.setattr(harness_module, "deflated_sharpe_ratio", fake_dsr)
    report = run_validation(
        {"A": "A", "B": "B"},
        plan,
        lambda candidate, segment: [0.01, -0.002, 0.008] * 12,
        ValidationGate(min_trades=1, min_deflated_sharpe=0.0, max_pbo=1.0),
    )
    assert report.deflated_sharpe == 0.75
    assert seen == [(108, 2)]


def test_preregistered_candidate_gate_requires_dev_and_selection_stability():
    base = _plan()
    plan = ValidationPlan(
        dev=base.dev,
        selection=base.selection,
        final=base.final,
        experiment={
            "candidate_gate": {
                "min_dev_trades": 3,
                "min_selection_trades": 3,
                "min_dev_expectancy": 0.0,
                "min_selection_expectancy": 0.0,
                "min_dev_profit_factor": 1.0,
                "min_selection_profit_factor": 1.0,
            }
        },
        block_length=base.block_length,
        bootstrap_replications=base.bootstrap_replications,
        bootstrap_seed=base.bootstrap_seed,
    )

    def evaluator(candidate, segment):
        if candidate == "unstable":
            return [-0.02, -0.01, 0.005] if segment.name == "dev" else [0.08, 0.07, 0.06]
        return [0.02, 0.01, -0.002]

    report = run_validation(
        {"unstable": "unstable", "stable": "stable"},
        plan,
        evaluator,
        ValidationGate(min_trades=1, min_deflated_sharpe=0.0, max_pbo=1.0),
    )
    assert report.selected_candidate == "stable"


def test_pbo_keeps_all_preregistered_trials_not_only_viable_winners(monkeypatch):
    base = _plan()
    plan = ValidationPlan(
        dev=base.dev,
        selection=base.selection,
        final=base.final,
        experiment={
            "candidate_gate": {
                "min_dev_trades": 3,
                "min_selection_trades": 3,
                "min_dev_expectancy": 0.0,
                "min_selection_expectancy": 0.0,
                "min_dev_profit_factor": 1.0,
                "min_selection_profit_factor": 1.0,
            }
        },
        block_length=base.block_length,
        bootstrap_replications=base.bootstrap_replications,
        bootstrap_seed=base.bootstrap_seed,
    )
    seen = []

    def fake_pbo(candidate_returns, n_blocks=6):
        seen.append(tuple(candidate_returns))
        return 0.25

    monkeypatch.setattr(harness_module, "estimate_pbo", fake_pbo)

    def evaluator(candidate, segment):
        if candidate == "loser":
            return [-0.03, -0.02, 0.001]
        return [0.03, 0.02, -0.001]

    run_validation(
        {"loser": "loser", "winner": "winner"},
        plan,
        evaluator,
        ValidationGate(min_trades=1, min_deflated_sharpe=0.0, max_pbo=1.0),
    )
    assert seen == [("loser", "winner")]
