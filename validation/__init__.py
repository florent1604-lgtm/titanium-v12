"""Pre-registered, dependency-aware validation helpers."""

from .harness import (
    CandidateResult,
    Segment,
    ValidationGate,
    ValidationPlan,
    ValidationReport,
    ValidationStatus,
    block_bootstrap,
    bootstrap_intervals,
    compute_metrics,
    deflated_sharpe_ratio,
    estimate_pbo,
    run_validation,
)

__all__ = [
    "CandidateResult",
    "Segment",
    "ValidationGate",
    "ValidationPlan",
    "ValidationReport",
    "ValidationStatus",
    "block_bootstrap",
    "bootstrap_intervals",
    "compute_metrics",
    "deflated_sharpe_ratio",
    "estimate_pbo",
    "run_validation",
]
