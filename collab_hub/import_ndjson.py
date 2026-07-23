"""Read-only, idempotent migration from the legacy collaboration NDJSON bus."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from .contracts import PRINCIPALS, MessageDraft
from .store import CollabStore


_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_KIND_MAP = {
    "ack": "ack",
    "handoff": "handoff",
    "question": "question",
    "review": "review",
    "decision": "decision",
    "presence": "presence",
    "alert": "alert",
}


@dataclass(frozen=True)
class ImportReport:
    imported: int
    duplicates: int
    skipped_security: int
    errors: tuple[dict, ...]


def _optional_opaque(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and _OPAQUE_RE.fullmatch(text) else None


def _legacy_draft(item: dict, source: Path, line_number: int) -> MessageDraft:
    message_id = _optional_opaque(item.get("id"))
    if message_id is None:
        raise ValueError("legacy id absent ou invalide")
    principal = str(item.get("from", "")).strip().lower()
    raw_target = str(item.get("to", "")).strip().lower()
    if principal not in PRINCIPALS:
        raise ValueError("legacy principal inconnu")
    target = {
        "all": "topic:team",
        "claude_or_codex": "topic:supervisors",
    }.get(raw_target, raw_target)
    if target not in PRINCIPALS and not target.startswith("topic:"):
        raise ValueError("legacy target inconnu")
    content = item.get("content") or item.get("body")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("legacy content absent")
    legacy_type = str(item.get("type", "message")).strip().lower()
    kind = _KIND_MAP.get(legacy_type, "status")
    classification = (
        "SENSITIVE_METADATA"
        if legacy_type == "gitnexus_write_request"
        else "INTERNAL"
    )
    return MessageDraft(
        principal=principal,
        target=target,
        kind=kind,
        content=content,
        idempotency_key=f"legacy:{message_id}",
        task_id=_optional_opaque(item.get("task")),
        correlation_id=None,
        in_reply_to=_optional_opaque(item.get("in_reply_to")),
        evidence_refs=(f"legacy:{source.name}:{line_number}",),
        classification=classification,
    )


def import_ndjson_paths(store: CollabStore, paths: Iterable[Path]) -> ImportReport:
    imported = 0
    duplicates = 0
    skipped_security = 0
    errors: list[dict] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            errors.append({"file": str(path), "line": 0, "error": "FILE_NOT_FOUND"})
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    item = json.loads(raw_line)
                    if not isinstance(item, dict):
                        raise ValueError("legacy row doit être un objet")
                    if str(item.get("type", "")).strip().lower() == (
                        "gitnexus_write_approval"
                    ):
                        skipped_security += 1
                        continue
                    receipt = store.publish(_legacy_draft(item, path, line_number))
                    if receipt.duplicate:
                        duplicates += 1
                    else:
                        imported += 1
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    errors.append(
                        {"file": str(path), "line": line_number, "error": str(exc)}
                    )
    return ImportReport(imported, duplicates, skipped_security, tuple(errors))
