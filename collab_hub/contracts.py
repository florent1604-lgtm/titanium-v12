"""Typed, bounded contracts for the local C1 collaboration plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


PRINCIPALS = frozenset({"florent", "claude", "codex", "hermes", "system"})
KINDS = frozenset(
    {"status", "handoff", "question", "review", "decision", "ack", "presence", "alert"}
)
CLASSIFICATIONS = frozenset({"PUBLIC", "INTERNAL", "SENSITIVE_METADATA"})
PRESENCE_STATES = frozenset({"ONLINE", "IDLE", "OFFLINE", "DEGRADED"})


@dataclass(frozen=True)
class MessageDraft:
    principal: str
    target: str
    kind: str
    content: str
    idempotency_key: str
    task_id: str | None = None
    correlation_id: str | None = None
    in_reply_to: str | None = None
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    classification: str = "INTERNAL"


@dataclass(frozen=True)
class PublishReceipt:
    message_id: str
    global_offset: int
    duplicate: bool
    content_sha256: str


@dataclass(frozen=True)
class StoredMessage:
    global_offset: int
    message_id: str
    schema_version: int
    created_at: str
    principal: str
    target: str
    kind: str
    content: str
    idempotency_key: str
    task_id: str | None
    correlation_id: str | None
    in_reply_to: str | None
    evidence_refs: Tuple[str, ...]
    classification: str
    content_sha256: str
