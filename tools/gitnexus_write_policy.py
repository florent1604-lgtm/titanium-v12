"""Fail-closed policy primitives for supervised GitNexus native writes."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import msvcrt


ROOT = Path(__file__).resolve().parent.parent
ALLOWED_REPO = "titanium-v12"
ALLOWED_TOOLS = frozenset({"rename", "group_sync"})
SUPERVISORS = frozenset({"claude", "codex"})
TTL_SECONDS = 900
SENSITIVE_PREFIXES = ("core/", "execution/", "domain/", "api/")
SENSITIVE_FILES = frozenset(
    {
        "utils/atomic_state.py",
        "tools/gitnexus_runtime.py",
        "tools/collab_bus.mjs",
    }
)
SENSITIVE_TERMS = ("trade", "order", "broker", "mt5")
SIGNATURE_ALGORITHM = "Ed25519"
SIGNED_APPROVAL_FIELDS = (
    "id",
    "type",
    "verdict",
    "from",
    "to",
    "in_reply_to",
    "ts_utc",
    "tool",
    "args_sha256",
    "file_fingerprint",
    "request_expires_ts",
    "nonce",
    "florent_override",
)


class GateRefused(RuntimeError):
    """Raised with a stable reason code when the write gate refuses a request."""


@dataclass(frozen=True)
class WriteRequest:
    request_id: str
    tool: Literal["rename", "group_sync"]
    args: dict[str, Any]
    args_sha256: str
    created_ts: datetime
    expires_ts: datetime
    impact_risk: str
    files: tuple[str, ...]
    file_fingerprint: str


@dataclass(frozen=True)
class ApprovalSet:
    supervisor: Literal["claude", "codex"]
    florent_override: bool


def _require_nonempty_string(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateRefused(reason)
    return value.strip()


def normalize_args(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return canonical native arguments for preparation, rejecting extra input."""
    if tool not in ALLOWED_TOOLS:
        raise GateRefused("TOOL_NOT_ALLOWED")
    if not isinstance(args, dict):
        raise GateRefused("ARGUMENTS_INVALID")

    repo = args.get("repo", ALLOWED_REPO)
    if repo != ALLOWED_REPO:
        raise GateRefused("REPO_NOT_ALLOWED")

    if tool == "rename":
        allowed = {
            "repo",
            "symbol_name",
            "symbol_uid",
            "new_name",
            "file_path",
            "dry_run",
            "branch",
        }
        unknown = set(args) - allowed
        if unknown:
            raise GateRefused("UNKNOWN_ARGUMENT")
        if args.get("dry_run", True) is not True:
            raise GateRefused("PREVIEW_REQUIRED")

        new_name = _require_nonempty_string(args.get("new_name"), "NEW_NAME_REQUIRED")
        symbol_name = args.get("symbol_name")
        symbol_uid = args.get("symbol_uid")
        if not any(isinstance(value, str) and value.strip() for value in (symbol_name, symbol_uid)):
            raise GateRefused("SYMBOL_REQUIRED")

        normalized: dict[str, Any] = {"repo": ALLOWED_REPO}
        for key in ("symbol_name", "symbol_uid", "file_path", "branch"):
            if key in args and args[key] is not None:
                normalized[key] = _require_nonempty_string(args[key], f"{key.upper()}_INVALID")
        normalized["new_name"] = new_name
        normalized["dry_run"] = True
        return normalized

    allowed = {"repo", "name", "skipEmbeddings", "exactOnly"}
    unknown = set(args) - allowed
    if unknown:
        raise GateRefused("UNKNOWN_ARGUMENT")
    normalized = {
        "repo": ALLOWED_REPO,
        "name": _require_nonempty_string(args.get("name"), "GROUP_NAME_REQUIRED"),
    }
    for key in ("skipEmbeddings", "exactOnly"):
        if key in args:
            if not isinstance(args[key], bool):
                raise GateRefused(f"{key.upper()}_INVALID")
            normalized[key] = args[key]
    return normalized


canonical_args = normalize_args


def args_sha256(args: dict[str, Any]) -> str:
    payload = json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_repo_path(path: str | Path, *, root: Path = ROOT) -> Path:
    root = root.resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise GateRefused("PATH_OUTSIDE_REPOSITORY")
    return resolved


def fingerprint_files(files: Sequence[str | Path], *, root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    root = root.resolve()
    normalized: list[tuple[str, Path]] = []
    for item in files:
        resolved = validate_repo_path(item, root=root)
        if not resolved.is_file():
            raise GateRefused("TARGET_FILE_MISSING")
        relative = resolved.relative_to(root).as_posix()
        normalized.append((relative, resolved))
    if not normalized:
        raise GateRefused("TARGET_FILES_EMPTY")
    for relative, resolved in sorted(normalized):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def classify_sensitive(files: Sequence[str | Path], impact_risk: str) -> bool:
    if str(impact_risk).upper() not in {"LOW", "MEDIUM"}:
        return True
    for item in files:
        normalized = str(item).replace("\\", "/").lower()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized.startswith(SENSITIVE_PREFIXES) or normalized in SENSITIVE_FILES:
            return True
        name = normalized.rsplit("/", 1)[-1]
        if name.startswith(".env") or any(term in normalized for term in SENSITIVE_TERMS):
            return True
    return False


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise GateRefused("APPROVAL_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateRefused("APPROVAL_INVALID") from exc
    if parsed.tzinfo is None:
        raise GateRefused("APPROVAL_INVALID")
    return parsed.astimezone(timezone.utc)


def canonical_approval_payload(approval: Mapping[str, Any]) -> bytes:
    """Return the exact detached-signature payload for an approval."""
    try:
        payload = {field: approval[field] for field in SIGNED_APPROVAL_FIELDS}
    except (KeyError, TypeError) as exc:
        raise GateRefused("SIGNATURE_INVALID") from exc
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_trusted_public_keys(path: str | Path) -> dict[str, dict[str, str]]:
    """Load the public-only approver registry; missing/empty is fail-closed."""
    try:
        decoded = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateRefused("SIGNATURE_KEYS_UNAVAILABLE") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GateRefused("SIGNATURE_KEYS_INVALID") from exc
    if not isinstance(decoded, dict) or decoded.get("version") != 1:
        raise GateRefused("SIGNATURE_KEYS_INVALID")
    rows = decoded.get("keys")
    if not isinstance(rows, list) or not rows:
        raise GateRefused("SIGNATURE_KEYS_UNAVAILABLE")
    trusted: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "key_id",
            "actor",
            "algorithm",
            "public_key_b64",
            "enabled",
        }:
            raise GateRefused("SIGNATURE_KEYS_INVALID")
        if row.get("enabled") is not True:
            continue
        key_id = row.get("key_id")
        actor = row.get("actor")
        algorithm = row.get("algorithm")
        public_key_b64 = row.get("public_key_b64")
        if (
            not isinstance(key_id, str)
            or not key_id.strip()
            or key_id in trusted
            or actor not in (SUPERVISORS | {"florent"})
            or algorithm != SIGNATURE_ALGORITHM
            or not isinstance(public_key_b64, str)
        ):
            raise GateRefused("SIGNATURE_KEYS_INVALID")
        trusted[key_id] = {
            "actor": actor,
            "algorithm": algorithm,
            "public_key_b64": public_key_b64,
        }
    if not trusted:
        raise GateRefused("SIGNATURE_KEYS_UNAVAILABLE")
    return trusted


def _verify_approval_signature(
    approval: dict[str, Any],
    trusted_public_keys: Mapping[str, Mapping[str, str]],
) -> None:
    signature = approval.get("signature")
    if not isinstance(signature, dict):
        raise GateRefused("SIGNATURE_REQUIRED")
    if set(signature) != {"algorithm", "key_id", "value_b64"}:
        raise GateRefused("SIGNATURE_INVALID")
    if signature.get("algorithm") != SIGNATURE_ALGORITHM:
        raise GateRefused("SIGNATURE_INVALID")
    key_id = signature.get("key_id")
    if not isinstance(key_id, str) or key_id not in trusted_public_keys:
        raise GateRefused("SIGNATURE_KEY_UNTRUSTED")
    trusted = trusted_public_keys[key_id]
    actor = str(approval.get("from", "")).lower()
    if trusted.get("actor") != actor:
        raise GateRefused("SIGNER_ACTOR_MISMATCH")
    if trusted.get("algorithm") != SIGNATURE_ALGORITHM:
        raise GateRefused("SIGNATURE_KEYS_INVALID")
    nonce = approval.get("nonce")
    if not isinstance(nonce, str) or not 16 <= len(nonce) <= 128:
        raise GateRefused("SIGNATURE_INVALID")
    try:
        public_key_raw = base64.b64decode(
            trusted["public_key_b64"], validate=True
        )
        signature_raw = base64.b64decode(signature["value_b64"], validate=True)
        if len(public_key_raw) != 32 or len(signature_raw) != 64:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(
            signature_raw,
            canonical_approval_payload(approval),
        )
    except (InvalidSignature, ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise GateRefused("SIGNATURE_INVALID") from exc


def _approval_matches(request: WriteRequest, approval: dict[str, Any]) -> bool:
    try:
        approval_expiry = _parse_timestamp(approval.get("request_expires_ts"))
    except GateRefused:
        return False
    return (
        approval.get("type") == "gitnexus_write_approval"
        and approval.get("verdict") == "APPROVED"
        and approval.get("to") == "hermes"
        and approval.get("in_reply_to") == request.request_id
        and approval.get("tool") == request.tool
        and approval.get("args_sha256") == request.args_sha256
        and approval.get("file_fingerprint") == request.file_fingerprint
        and approval_expiry == request.expires_ts.astimezone(timezone.utc)
    )


def find_valid_approvals(
    request: WriteRequest,
    approvals: Sequence[dict[str, Any]],
    *,
    trusted_public_keys: Mapping[str, Mapping[str, str]],
    require_florent_all: bool = True,
    now: datetime | None = None,
) -> ApprovalSet:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now > request.expires_ts.astimezone(timezone.utc):
        raise GateRefused("APPROVAL_EXPIRED")

    related = [item for item in approvals if item.get("in_reply_to") == request.request_id]
    if not related:
        raise GateRefused("APPROVAL_REQUIRED")
    if any(not _approval_matches(request, item) for item in related):
        raise GateRefused("APPROVAL_MISMATCH")

    valid: list[dict[str, Any]] = []
    saw_expired = False
    for approval in related:
        _verify_approval_signature(approval, trusted_public_keys)
        approved_at = _parse_timestamp(approval.get("ts_utc"))
        age = (now - approved_at).total_seconds()
        if age < 0 or age > TTL_SECONDS or approved_at > request.expires_ts:
            saw_expired = True
            continue
        valid.append(approval)

    supervisor = next(
        (item for item in valid if str(item.get("from", "")).lower() in SUPERVISORS),
        None,
    )
    if supervisor is None:
        if saw_expired:
            raise GateRefused("APPROVAL_EXPIRED")
        raise GateRefused("SUPERVISOR_REQUIRED")

    sensitive = classify_sensitive(request.files, request.impact_risk)
    florent = next(
        (
            item
            for item in valid
            if str(item.get("from", "")).lower() == "florent"
            and item.get("florent_override") is True
        ),
        None,
    )
    if (require_florent_all or sensitive) and florent is None:
        raise GateRefused("FLORENT_REQUIRED")

    return ApprovalSet(
        supervisor=str(supervisor["from"]).lower(),
        florent_override=florent is not None,
    )


class ExecutionLedger:
    """Atomic single-use claim ledger guarded by a Windows file lock."""

    def __init__(self, path: Path, lock_path: Path) -> None:
        self.path = Path(path)
        self.lock_path = Path(lock_path)

    def consume_once(self, request_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                if self.path.exists():
                    for line in self.path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise GateRefused("LEDGER_CORRUPT") from exc
                        if row.get("request_id") == request_id:
                            raise GateRefused("APPROVAL_REPLAY")
                row = {
                    "request_id": request_id,
                    "status": "CLAIMED",
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                }
                with self.path.open("a", encoding="utf-8", newline="\n") as ledger:
                    ledger.write(json.dumps(row, sort_keys=True) + "\n")
                    ledger.flush()
                    os.fsync(ledger.fileno())
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
