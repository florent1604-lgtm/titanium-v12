"""Versioned contracts for CollabHub's durable manual task workflow."""

from __future__ import annotations

from dataclasses import dataclass


TASK_SCHEMA_VERSION = 1
TASK_STATES = (
    "NOUVEAU",
    "A_ANALYSER",
    "CORRECTIF_EN_COURS",
    "A_REVALIDER",
    "CLOS",
)
FAILURE_REASONS = frozenset(
    {
        "SERVICE_UNAVAILABLE",
        "VALIDATION_REJECTED",
        "PERMISSION_REQUIRED",
        "TIMEOUT",
        "TEST_FAILED",
        "GUARD_TRIGGERED",
        "CONFLICT",
        "UNKNOWN_FAILURE",
    }
)
TASK_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})


@dataclass(frozen=True)
class TaskDraft:
    title: str
    owner: str
    priority: str


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    title: str
    owner: str
    priority: str
    status: str
    attempt_id: str
    requested_by: str
    event_id: str
    created_at: str
    updated_at: str
    payload_sha256: str


@dataclass(frozen=True)
class AttemptFailure:
    task_id: str
    attempt_id: str
    reason_code: str
    evidence_ref: str
    status: str
    event_id: str
    created_at: str
    payload_sha256: str
