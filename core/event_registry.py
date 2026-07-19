"""Frozen EventPlane v1 registry and pre-persistence secret gate.

This module validates facts only. It has no dependency on trading, execution,
MT5, NATS, or the API layer.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "docs" / "contracts" / "eventplane-v1-registry.json"
DIGEST_PATH = ROOT / "docs" / "contracts" / "eventplane-v1-registry.sha256"
EXPECTED_REGISTRY_SHA256 = (
    "6CE8BC5DAC6B79C6339CF20BA38D28C9D454A9914CFAB55491BFDFB8A72E8BEA"
)


class RegistryViolation(ValueError):
    """A fact does not conform to the frozen EventPlane registry."""


class RegistryDigestMismatch(RegistryViolation):
    """The registry bytes or companion digest changed without a version bump."""


class SecretDetected(RegistryViolation):
    """Potential secret rejected before it can reach the immutable journal."""


_DENIED_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "token",
    "x_admin_token",
}
_DENIED_SUFFIXES = ("_api_key", "_password", "_private_key", "_secret", "_token")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:live|test|proj)-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
)


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _secret_path(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "$"


def assert_secret_free(value: Any, *, _path: tuple[str, ...] = ()) -> None:
    """Reject obvious credentials without ever copying their value to an error."""
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = _normalized_key(raw_key)
            path = (*_path, key or "?")
            if key in _DENIED_KEYS or key.endswith(_DENIED_SUFFIXES):
                raise SecretDetected(f"SECRET_DETECTED:{_secret_path(path)}")
            assert_secret_free(nested, _path=path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            assert_secret_free(nested, _path=(*_path, str(index)))
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        raise SecretDetected(f"SECRET_DETECTED:{_secret_path(_path)}")


@lru_cache(maxsize=1)
def load_registry() -> dict:
    """Load the frozen registry only when both the companion and bytes match."""
    raw = REGISTRY_PATH.read_bytes()
    companion = DIGEST_PATH.read_text(encoding="ascii").split()[0].upper()
    actual = hashlib.sha256(raw).hexdigest().upper()
    if not secrets.compare_digest(companion, EXPECTED_REGISTRY_SHA256):
        raise RegistryDigestMismatch("REGISTRY_COMPANION_DIGEST_MISMATCH")
    if not secrets.compare_digest(actual, EXPECTED_REGISTRY_SHA256):
        raise RegistryDigestMismatch("REGISTRY_DIGEST_MISMATCH")

    registry = json.loads(raw.decode("utf-8"))
    if registry.get("registry_version") != "eventplane-registry/1.0.0":
        raise RegistryViolation("REGISTRY_VERSION_MISMATCH")
    if registry.get("status") != "FROZEN":
        raise RegistryViolation("REGISTRY_NOT_FROZEN")
    if registry.get("compatibility") != "CLOSED_EXACT":
        raise RegistryViolation("REGISTRY_NOT_CLOSED_EXACT")
    if not isinstance(registry.get("types"), dict):
        raise RegistryViolation("REGISTRY_TYPES_INVALID")
    return registry


def validate_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    """Validate a payload against one exact registered event schema."""
    registry = load_registry()
    definition = registry["types"].get(event_type)
    if definition is None:
        raise RegistryViolation("UNKNOWN_EVENT_TYPE")
    if not isinstance(payload, Mapping):
        raise RegistryViolation("PAYLOAD_NOT_OBJECT")

    assert_secret_free(payload)
    schema = {
        "$schema": registry["$schema"],
        "$defs": registry["$defs"],
        **definition["payload_schema"],
    }
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(payload)),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise RegistryViolation(
            f"PAYLOAD_SCHEMA_VIOLATION:{path}:{first.validator}"
        )

