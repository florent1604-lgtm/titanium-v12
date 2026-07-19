from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

try:
    from tools.gitnexus_runtime import RUNTIME_ROOT
except ModuleNotFoundError:  # Direct execution: python tools/<script>.py
    from gitnexus_runtime import RUNTIME_ROOT


STATUS_PATH = RUNTIME_ROOT / "claude-gitnexus-status.json"
ENDPOINT = "http://127.0.0.1:4747/api/mcp"
MAX_AGE_SECONDS = 86_400
RISK_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
PUBLIC_ATTESTATION_FIELDS = (
    "identity",
    "configured",
    "verified_at",
    "verification_fresh",
    "transport",
    "endpoint_scope",
    "access",
    "billing_guard",
    "selected_provider",
    "fallback",
)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "none",
    }


def assess_billing(
    auth: Mapping[str, object], env: Mapping[str, str]
) -> str:
    if any(_truthy(env.get(key)) for key in RISK_ENV_KEYS):
        return "API_BILLING_RISK"
    if not auth or auth.get("loggedIn") is not True:
        return "UNVERIFIED"
    if (
        auth.get("authMethod") == "claude.ai"
        and auth.get("apiProvider") == "firstParty"
        and str(auth.get("subscriptionType", "")).lower() in {"pro", "max"}
    ):
        return "SUBSCRIPTION_OK"
    return "API_BILLING_RISK"


def build_public_attestation(
    auth: Mapping[str, object],
    env: Mapping[str, str],
    *,
    mcp_verified: bool,
    verified_at: datetime,
) -> dict[str, object]:
    guard = assess_billing(auth, env) if mcp_verified else "UNVERIFIED"
    return {
        "identity": "claude",
        "configured": bool(mcp_verified),
        "verified_at": verified_at.astimezone(timezone.utc).isoformat(),
        "verification_fresh": bool(mcp_verified),
        "transport": "http",
        "endpoint_scope": "loopback",
        "access": "native-read-only",
        "billing_guard": guard,
        "selected_provider": "claude" if guard == "SUBSCRIPTION_OK" else "ollama",
        "fallback": "ollama:qwen2.5:7b",
    }


def _default_status() -> dict[str, object]:
    return build_public_attestation(
        {},
        {},
        mcp_verified=False,
        verified_at=datetime.now(timezone.utc),
    )


def _public_attestation(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        field: payload[field]
        for field in PUBLIC_ATTESTATION_FIELDS
        if field in payload
    }


def _attestation_contract_valid(payload: Mapping[str, object]) -> bool:
    if set(payload) != set(PUBLIC_ATTESTATION_FIELDS):
        return False
    if payload.get("identity") != "claude":
        return False
    if payload.get("transport") != "http":
        return False
    if payload.get("endpoint_scope") != "loopback":
        return False
    if payload.get("access") != "native-read-only":
        return False
    if payload.get("fallback") != "ollama:qwen2.5:7b":
        return False
    if type(payload.get("configured")) is not bool:
        return False
    if type(payload.get("verification_fresh")) is not bool:
        return False

    guard = payload.get("billing_guard")
    provider = payload.get("selected_provider")
    if guard == "SUBSCRIPTION_OK":
        return (
            payload["configured"] is True
            and payload["verification_fresh"] is True
            and provider == "claude"
        )
    if guard == "API_BILLING_RISK":
        return (
            payload["configured"] is True
            and payload["verification_fresh"] is True
            and provider == "ollama"
        )
    if guard == "UNVERIFIED":
        return (
            payload["configured"] is False
            and payload["verification_fresh"] is False
            and provider == "ollama"
        )
    return False


def write_attestation(
    payload: Mapping[str, object], path: Path = STATUS_PATH
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(_public_attestation(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def read_attestation(
    path: Path = STATUS_PATH, *, now: datetime | None = None
) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw_payload, dict):
            raise TypeError("attestation must be a JSON object")
        payload = _public_attestation(raw_payload)
        if not _attestation_contract_valid(payload):
            raise ValueError("attestation contract invalid")
        verified_at = datetime.fromisoformat(str(payload["verified_at"]))
        if verified_at.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _default_status()

    age = (
        current.astimezone(timezone.utc)
        - verified_at.astimezone(timezone.utc)
    ).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        payload.update(
            {
                "verification_fresh": False,
                "billing_guard": "UNVERIFIED",
                "selected_provider": "ollama",
            }
        )
    return payload


def attest_current(
    claude_exe: Path, *, mcp_verified: bool
) -> dict[str, object]:
    result = subprocess.run(
        [str(claude_exe), "auth", "status"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        auth = json.loads(result.stdout) if result.returncode == 0 else {}
    except json.JSONDecodeError:
        auth = {}
    payload = build_public_attestation(
        auth,
        {key: os.environ.get(key, "") for key in RISK_ENV_KEYS},
        mcp_verified=mcp_verified,
        verified_at=datetime.now(timezone.utc),
    )
    write_attestation(payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    attest = sub.add_parser("attest")
    attest.add_argument("--claude-exe", type=Path, required=True)
    attest.add_argument("--mcp-verified", action="store_true")
    args = parser.parse_args(argv)
    payload = attest_current(args.claude_exe, mcp_verified=args.mcp_verified)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["billing_guard"] == "SUBSCRIPTION_OK" else 78


if __name__ == "__main__":
    raise SystemExit(main())
