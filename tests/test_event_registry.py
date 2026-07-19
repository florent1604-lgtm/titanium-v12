"""Frozen EventPlane registry and pre-persistence secret gate."""
from __future__ import annotations

import pytest

from core.event_registry import (
    EXPECTED_REGISTRY_SHA256,
    RegistryViolation,
    SecretDetected,
    assert_secret_free,
    load_registry,
    validate_payload,
)


VALID_C0A = {
    "decision_id": "d-btc-1",
    "as_of": "2026-07-19T07:30:00+00:00",
    "state_version": "confluence/1.1.0",
    "result": "BLOCK",
    "side": "short",
    "reason_codes": ["BLOCK_PILLAR_MISSING"],
    "data_valid": True,
    "setup_family": "reversal",
    "rank": 2.0,
    "n_pillars": 2,
    "aggressive_eligible": False,
    "decision_capability": False,
    "orders_capability": False,
}


def test_registry_is_frozen_with_expected_digest():
    registry = load_registry()
    assert EXPECTED_REGISTRY_SHA256 == (
        "6CE8BC5DAC6B79C6339CF20BA38D28C9D454A9914CFAB55491BFDFB8A72E8BEA"
    )
    assert registry["registry_version"] == "eventplane-registry/1.0.0"
    assert registry["status"] == "FROZEN"
    assert registry["compatibility"] == "CLOSED_EXACT"
    assert len(registry["types"]) == 14


def test_exact_c0a_payload_is_valid():
    validate_payload("confluence.evaluation.completed.v1", VALID_C0A)


def test_closed_registry_rejects_unknown_type():
    with pytest.raises(RegistryViolation, match="UNKNOWN_EVENT_TYPE"):
        validate_payload("unknown.fact.v1", {})


def test_closed_registry_rejects_extra_property():
    with pytest.raises(RegistryViolation, match="additionalProperties"):
        validate_payload(
            "confluence.evaluation.completed.v1",
            {**VALID_C0A, "verdict": "BLOCK"},
        )


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "authorization",
        "password",
        "private_key",
        "secret",
        "token",
        "x_admin_token",
    ],
)
def test_sensitive_keys_are_rejected_without_leaking_values(key):
    leaked = "sk-live-never-print-this"
    with pytest.raises(SecretDetected, match="SECRET_DETECTED") as caught:
        assert_secret_free({"nested": [{key: leaked}]})
    assert leaked not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN PRIVATE KEY-----",
        "sk-live-abcdefghijklmnopqrstuvwxyz012345",
    ],
)
def test_obvious_secret_values_are_rejected_without_echo(value):
    with pytest.raises(SecretDetected, match="SECRET_DETECTED") as caught:
        assert_secret_free({"message": value})
    assert value not in str(caught.value)

