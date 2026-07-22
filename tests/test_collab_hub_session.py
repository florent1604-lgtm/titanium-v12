from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from collab_hub.secret_gate import scan_text
from collab_hub.session import (
    InvalidSession,
    SessionAuthority,
    SessionError,
    SessionExpired,
)
from collab_hub.windows_attestation import (
    AttestationError,
    ChallengeExpired,
    KeyProtectionError,
    ProofRejected,
    ReplayRejected,
    WindowsAttestation,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class RecordingProtector:
    def __init__(self) -> None:
        self.protected: list[bytes] = []

    def protect(self, value: bytes) -> bytes:
        self.protected.append(value)
        return b"protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"protected:"):
            raise ValueError("invalid protected payload")
        return value.removeprefix(b"protected:")[::-1]


class FailingProtector:
    def protect(self, value: bytes) -> bytes:
        raise RuntimeError("protector unavailable")

    def unprotect(self, value: bytes) -> bytes:
        raise RuntimeError("protector unavailable")


def _attestation(
    tmp_path: Path,
    clock: FakeClock,
    protector: object | None = None,
    max_challenges: int = 1024,
) -> WindowsAttestation:
    return WindowsAttestation(
        clock=clock,
        key_path=tmp_path / "session.key.dpapi",
        protector=protector or RecordingProtector(),
        acl_hardener=lambda _path: None,
        max_challenges=max_challenges,
    )


def test_secret_gate_rejects_bearer_and_private_key() -> None:
    assert scan_text("Authorization: Bearer abcdefghijklmnop") == ("BEARER_TOKEN",)
    assert scan_text("-----BEGIN PRIVATE KEY-----") == ("PRIVATE_KEY",)


def test_secret_gate_returns_deduplicated_fixed_reason_codes() -> None:
    value = (
        "authorization: bearer first\n"
        "Authorization: Bearer second\n"
        "-----BEGIN RSA PRIVATE KEY-----"
    )

    assert scan_text(value) == ("BEARER_TOKEN", "PRIVATE_KEY")


def test_secret_gate_rejects_credentials_without_returning_their_values() -> None:
    samples = (
        "password=" + "not-a-real-credential-42",
        "token=" + "not-a-real-session-token-42",
        "api_key=" + "not-a-real-api-key-42",
        "Bearer " + "not-a-real-bearer-token-42",
    )

    assert tuple(scan_text(sample) for sample in samples) == (
        ("PASSWORD",),
        ("TOKEN",),
        ("API_KEY",),
        ("BEARER_TOKEN",),
    )


def test_secret_gate_avoids_manifest_assignment_name_false_positives() -> None:
    harmless = (
        "password_policy=strict token_count=4 api_key_name=primary; "
        "use bearer authentication"
    )

    assert scan_text(harmless) == ()


def test_session_expires_and_never_serializes_token() -> None:
    clock = FakeClock()
    authority = SessionAuthority(clock=clock, ttl_seconds=900)

    issued = authority.issue("S-1-5-21-test")

    assert authority.verify(issued.token).windows_sid == "S-1-5-21-test"
    assert "token" not in authority.audit_view(issued)
    assert issued.token not in repr(vars(authority))
    clock.advance(901)
    with pytest.raises(SessionExpired):
        authority.verify(issued.token)


def test_session_rejects_unknown_tokens() -> None:
    authority = SessionAuthority(clock=FakeClock(), ttl_seconds=900)

    with pytest.raises(InvalidSession):
        authority.verify("unknown-token")


def test_session_records_are_pruned_when_new_sessions_are_issued() -> None:
    clock = FakeClock()
    authority = SessionAuthority(clock=clock, ttl_seconds=900)
    expired = authority.issue("S-1-5-21-first")

    clock.advance(901)
    authority.issue("S-1-5-21-second")

    assert expired.token not in repr(vars(authority))
    assert len(authority._sessions) == 1
    with pytest.raises(InvalidSession):
        authority.verify(expired.token)


def test_session_verify_prunes_expired_records_for_unknown_token() -> None:
    clock = FakeClock()
    authority = SessionAuthority(clock=clock, ttl_seconds=10)
    authority.issue("S-1-5-21-expired")

    clock.advance(10)

    with pytest.raises(InvalidSession):
        authority.verify("unknown-token")
    assert authority._sessions == {}


def test_session_capacity_refuses_a_new_live_session() -> None:
    authority = SessionAuthority(
        clock=FakeClock(), ttl_seconds=900, max_sessions=2
    )
    authority.issue("S-1-5-21-first")
    authority.issue("S-1-5-21-second")

    with pytest.raises(SessionError, match="SESSION_CAPACITY_EXCEEDED"):
        authority.issue("S-1-5-21-third")


def test_windows_proof_is_bound_to_sid_and_single_use(tmp_path: Path) -> None:
    attestation = _attestation(tmp_path, FakeClock())
    nonce = attestation.challenge()
    proof = attestation.test_proof("S-1-5-21-florent", nonce)

    with pytest.raises(ProofRejected):
        attestation.verify("S-1-5-21-intruder", nonce, proof)
    with pytest.raises(ReplayRejected):
        attestation.verify("S-1-5-21-florent", nonce, proof)

    fresh_nonce = attestation.challenge()
    fresh_proof = attestation.test_proof("S-1-5-21-florent", fresh_nonce)
    attestation.verify("S-1-5-21-florent", fresh_nonce, fresh_proof)
    with pytest.raises(ReplayRejected):
        attestation.verify("S-1-5-21-florent", fresh_nonce, fresh_proof)


def test_windows_nonce_expires_after_thirty_seconds(tmp_path: Path) -> None:
    clock = FakeClock()
    attestation = _attestation(tmp_path, clock)
    nonce = attestation.challenge()
    proof = attestation.test_proof("S-1-5-21-florent", nonce)

    clock.advance(30)

    with pytest.raises(ChallengeExpired):
        attestation.verify("S-1-5-21-florent", nonce, proof)


def test_challenge_operation_prunes_expired_challenges(tmp_path: Path) -> None:
    clock = FakeClock()
    attestation = _attestation(tmp_path, clock)
    expired = attestation.challenge()

    clock.advance(30)
    live = attestation.challenge()

    assert tuple(attestation._challenges) == (live,)
    with pytest.raises(ReplayRejected):
        attestation.verify("S-1-5-21-florent", expired, "unused-proof")


def test_proof_operation_prunes_other_expired_challenges(tmp_path: Path) -> None:
    clock = FakeClock()
    attestation = _attestation(tmp_path, clock)
    expired = attestation.challenge()
    clock.advance(29)
    live = attestation.challenge()
    clock.advance(1)

    attestation.test_proof("S-1-5-21-florent", live)

    assert expired not in attestation._challenges
    assert live in attestation._challenges


def test_verify_operation_prunes_expired_and_consumed_challenges(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    attestation = _attestation(tmp_path, clock)
    attestation.challenge()
    clock.advance(29)
    live = attestation.challenge()
    proof = attestation.test_proof("S-1-5-21-florent", live)
    clock.advance(1)

    attestation.verify("S-1-5-21-florent", live, proof)

    assert attestation._challenges == {}


def test_challenge_capacity_refuses_a_new_live_nonce(tmp_path: Path) -> None:
    attestation = _attestation(
        tmp_path, FakeClock(), max_challenges=2
    )
    attestation.challenge()
    attestation.challenge()

    with pytest.raises(AttestationError, match="CHALLENGE_CAPACITY_EXCEEDED"):
        attestation.challenge()


def test_bootstrap_key_is_persisted_only_through_protector(tmp_path: Path) -> None:
    clock = FakeClock()
    protector = RecordingProtector()
    key_path = tmp_path / "session.key.dpapi"

    first = _attestation(tmp_path, clock, protector)
    persisted = key_path.read_bytes()
    second = _attestation(tmp_path, clock, protector)

    assert len(protector.protected) == 1
    assert len(protector.protected[0]) == 32
    assert persisted != protector.protected[0]
    second_nonce = second.challenge()
    second_proof = second.test_proof("S-1-5-21-florent", second_nonce)
    second.verify("S-1-5-21-florent", second_nonce, second_proof)


def test_bootstrap_key_has_no_plaintext_fallback(tmp_path: Path) -> None:
    key_path = tmp_path / "session.key.dpapi"

    with pytest.raises(KeyProtectionError):
        _attestation(tmp_path, FakeClock(), FailingProtector())

    assert not key_path.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI CurrentUser is Windows-only")
def test_default_windows_protection_round_trip(tmp_path: Path) -> None:
    key_path = tmp_path / "command-deck" / "session.key.dpapi"
    attestation = WindowsAttestation(key_path=key_path)
    reloaded = WindowsAttestation(key_path=key_path)
    nonce = reloaded.challenge()
    proof = reloaded.test_proof("S-1-5-21-florent", nonce)

    reloaded.verify("S-1-5-21-florent", nonce, proof)

    assert attestation is not reloaded
    assert key_path.is_file()
    assert key_path.read_bytes()
