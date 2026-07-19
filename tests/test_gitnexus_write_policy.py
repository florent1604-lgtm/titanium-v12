from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import json
from pathlib import Path
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from tools import gitnexus_write_policy as policy


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def test_default_root_is_derived_from_the_checked_out_project() -> None:
    assert policy.ROOT == Path(__file__).resolve().parents[1]
    assert "C:\\Users\\" not in Path("tools/gitnexus_write_policy.py").read_text(
        encoding="utf-8"
    )


def make_signer(actor: str) -> tuple[Ed25519PrivateKey, dict[str, dict[str, str]]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = f"{actor}-test-key"
    return private_key, {
        key_id: {
            "actor": actor,
            "algorithm": "Ed25519",
            "public_key_b64": base64.b64encode(public_key).decode("ascii"),
        }
    }


def make_request(
    tmp_path: Path,
    *,
    risk: str = "LOW",
    files: list[str] | None = None,
) -> policy.WriteRequest:
    selected_files = files or ["sample.py"]
    for relative in selected_files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("value = 1\n", encoding="utf-8")
    args = {
        "repo": "titanium-v12",
        "symbol_name": "old_name",
        "new_name": "new_name",
        "dry_run": True,
    }
    return policy.WriteRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        tool="rename",
        args=args,
        args_sha256=policy.args_sha256(args),
        created_ts=NOW - timedelta(seconds=30),
        expires_ts=NOW + timedelta(seconds=870),
        impact_risk=risk,
        files=tuple(selected_files),
        file_fingerprint=policy.fingerprint_files(selected_files, root=tmp_path),
    )


def make_approval(
    request: policy.WriteRequest,
    *,
    actor: str,
    age_seconds: int = 30,
    florent_override: bool = False,
    private_key: Ed25519PrivateKey | None = None,
    key_id: str | None = None,
) -> dict[str, object]:
    approval: dict[str, object] = {
        "id": f"approval-{actor}",
        "type": "gitnexus_write_approval",
        "verdict": "APPROVED",
        "from": actor,
        "to": "hermes",
        "in_reply_to": request.request_id,
        "ts_utc": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "tool": request.tool,
        "args_sha256": request.args_sha256,
        "file_fingerprint": request.file_fingerprint,
        "request_expires_ts": request.expires_ts.isoformat(),
        "nonce": secrets.token_hex(16),
        "florent_override": florent_override,
    }
    if private_key is not None and key_id is not None:
        approval["signature"] = {
            "algorithm": "Ed25519",
            "key_id": key_id,
            "value_b64": base64.b64encode(
                private_key.sign(policy.canonical_approval_payload(approval))
            ).decode("ascii"),
        }
    return approval


def test_only_native_tools_and_v12_repo_are_allowed() -> None:
    normalized = policy.normalize_args(
        "rename",
        {"repo": "titanium-v12", "symbol_name": "old", "new_name": "new"},
    )
    assert normalized == {
        "repo": "titanium-v12",
        "symbol_name": "old",
        "new_name": "new",
        "dry_run": True,
    }

    with pytest.raises(policy.GateRefused, match="TOOL_NOT_ALLOWED"):
        policy.normalize_args("cypher", {})
    with pytest.raises(policy.GateRefused, match="REPO_NOT_ALLOWED"):
        policy.normalize_args(
            "rename",
            {"repo": "jarvis-runtime", "symbol_name": "old", "new_name": "new"},
        )
    with pytest.raises(policy.GateRefused, match="UNKNOWN_ARGUMENT"):
        policy.normalize_args(
            "rename",
            {"symbol_name": "old", "new_name": "new", "command": "whoami"},
        )


def test_repository_paths_cannot_escape_v12(tmp_path: Path) -> None:
    inside = tmp_path / "api" / "routes.py"
    inside.parent.mkdir()
    inside.write_text("pass\n", encoding="utf-8")
    assert policy.validate_repo_path("api/routes.py", root=tmp_path) == inside.resolve()

    with pytest.raises(policy.GateRefused, match="PATH_OUTSIDE_REPOSITORY"):
        policy.validate_repo_path("../outside.py", root=tmp_path)
    with pytest.raises(policy.GateRefused, match="PATH_OUTSIDE_REPOSITORY"):
        policy.validate_repo_path(str(tmp_path.parent / "outside.py"), root=tmp_path)


def test_file_fingerprint_changes_when_target_changes(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("before\n", encoding="utf-8")
    before = policy.fingerprint_files(["sample.py"], root=tmp_path)
    target.write_text("after\n", encoding="utf-8")
    after = policy.fingerprint_files(["sample.py"], root=tmp_path)
    assert before != after


def test_approval_is_exact_fresh_and_single_use(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    private_key, trusted_keys = make_signer("codex")
    key_id = next(iter(trusted_keys))
    approval = make_approval(
        request,
        actor="codex",
        age_seconds=899,
        private_key=private_key,
        key_id=key_id,
    )
    result = policy.find_valid_approvals(
        request,
        [approval],
        trusted_public_keys=trusted_keys,
        require_florent_all=False,
        now=NOW,
    )
    assert result.supervisor == "codex"

    expired = make_approval(
        request,
        actor="codex",
        age_seconds=901,
        private_key=private_key,
        key_id=key_id,
    )
    with pytest.raises(policy.GateRefused, match="APPROVAL_EXPIRED"):
        policy.find_valid_approvals(
            request,
            [expired],
            trusted_public_keys=trusted_keys,
            require_florent_all=False,
            now=NOW,
        )

    wrong_hash = {**approval, "args_sha256": "f" * 64}
    with pytest.raises(policy.GateRefused, match="APPROVAL_MISMATCH|SIGNATURE_INVALID"):
        policy.find_valid_approvals(
            request,
            [wrong_hash],
            trusted_public_keys=trusted_keys,
            require_florent_all=False,
            now=NOW,
        )

    ledger = policy.ExecutionLedger(
        tmp_path / "executions.ndjson",
        tmp_path / "gate.lock",
    )
    ledger.consume_once(request.request_id)
    with pytest.raises(policy.GateRefused, match="APPROVAL_REPLAY"):
        ledger.consume_once(request.request_id)
    row = json.loads((tmp_path / "executions.ndjson").read_text(encoding="utf-8"))
    assert row["status"] == "CLAIMED"


def test_sensitive_or_high_risk_requires_florent_and_supervisor(tmp_path: Path) -> None:
    request = make_request(tmp_path, risk="HIGH", files=["api/swing_routes.py"])
    supervisor_key, supervisor_keys = make_signer("claude")
    florent_key, florent_keys = make_signer("florent")
    trusted_keys = {**supervisor_keys, **florent_keys}
    supervisor = make_approval(
        request,
        actor="claude",
        private_key=supervisor_key,
        key_id=next(iter(supervisor_keys)),
    )
    with pytest.raises(policy.GateRefused, match="FLORENT_REQUIRED"):
        policy.find_valid_approvals(
            request,
            [supervisor],
            trusted_public_keys=trusted_keys,
            now=NOW,
        )

    florent = make_approval(
        request,
        actor="florent",
        florent_override=True,
        private_key=florent_key,
        key_id=next(iter(florent_keys)),
    )
    result = policy.find_valid_approvals(
        request,
        [supervisor, florent],
        trusted_public_keys=trusted_keys,
        now=NOW,
    )
    assert result.supervisor == "claude"
    assert result.florent_override is True


def test_unsigned_or_forged_actor_approval_is_rejected(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    unsigned = make_approval(request, actor="codex")
    _, trusted_keys = make_signer("codex")
    with pytest.raises(policy.GateRefused, match="SIGNATURE_REQUIRED"):
        policy.find_valid_approvals(
            request,
            [unsigned],
            trusted_public_keys=trusted_keys,
            require_florent_all=False,
            now=NOW,
        )

    private_key, claude_keys = make_signer("claude")
    forged = make_approval(
        request,
        actor="codex",
        private_key=private_key,
        key_id=next(iter(claude_keys)),
    )
    with pytest.raises(policy.GateRefused, match="SIGNER_ACTOR_MISMATCH"):
        policy.find_valid_approvals(
            request,
            [forged],
            trusted_public_keys=claude_keys,
            require_florent_all=False,
            now=NOW,
        )


def test_signature_binds_fingerprint_expiry_nonce_and_override(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    private_key, trusted_keys = make_signer("codex")
    approval = make_approval(
        request,
        actor="codex",
        private_key=private_key,
        key_id=next(iter(trusted_keys)),
    )
    for field, replacement in (
        ("file_fingerprint", "f" * 64),
        ("request_expires_ts", (NOW + timedelta(hours=2)).isoformat()),
        ("nonce", "forged-nonce"),
        ("florent_override", True),
    ):
        tampered = {**approval, field: replacement}
        with pytest.raises(policy.GateRefused, match="SIGNATURE_INVALID|APPROVAL_MISMATCH"):
            policy.find_valid_approvals(
                request,
                [tampered],
                trusted_public_keys=trusted_keys,
                require_florent_all=False,
                now=NOW,
            )


def test_default_policy_requires_florent_signature_for_every_write(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    supervisor_key, supervisor_keys = make_signer("codex")
    supervisor = make_approval(
        request,
        actor="codex",
        private_key=supervisor_key,
        key_id=next(iter(supervisor_keys)),
    )
    with pytest.raises(policy.GateRefused, match="FLORENT_REQUIRED"):
        policy.find_valid_approvals(
            request,
            [supervisor],
            trusted_public_keys=supervisor_keys,
            now=NOW,
        )


@pytest.mark.parametrize("enabled", [True, False])
def test_public_key_registry_refuses_private_or_unknown_key_material(
    tmp_path: Path,
    enabled: bool,
) -> None:
    _, trusted_keys = make_signer("codex")
    key_id, record = next(iter(trusted_keys.items()))
    registry = tmp_path / "keys.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "keys": [
                    {
                        "key_id": key_id,
                        **record,
                        "enabled": enabled,
                        "private_key_b64": "must-never-be-here",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(policy.GateRefused, match="SIGNATURE_KEYS_INVALID"):
        policy.load_trusted_public_keys(registry)


def test_unknown_impact_risk_is_sensitive_fail_closed() -> None:
    assert policy.classify_sensitive(["sample.py"], "UNKNOWN") is True


@pytest.mark.parametrize(
    "path",
    [
        "core/signal_engine.py",
        "execution/demo_mt5_executor.py",
        "domain/models.py",
        "api/swing_routes.py",
        "utils/atomic_state.py",
        "data/trade_journal.jsonl",
        ".env",
    ],
)
def test_sensitive_paths_are_classified_fail_closed(path: str) -> None:
    assert policy.classify_sensitive([path], "LOW") is True
