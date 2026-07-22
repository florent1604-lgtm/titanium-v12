"""Current-user protected bootstrap key and one-shot Windows attestations."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import secrets
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


class AttestationError(Exception):
    """Base error for the local Windows attestation protocol."""


class KeyProtectionError(AttestationError):
    """Raised when the bootstrap key cannot remain OS-protected."""


class ReplayRejected(AttestationError):
    """Raised when a nonce is missing or has already been consumed."""


class ChallengeExpired(AttestationError):
    """Raised when a nonce exceeded its short validity window."""


class ProofRejected(AttestationError):
    """Raised when a proof is not valid for the SID and nonce."""


class ChallengeCapacityExceeded(AttestationError):
    """Raised when all bounded challenge slots contain live nonces."""


class KeyProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class DpapiCurrentUserProtector:
    """Protect bytes with Windows DPAPI in the current-user scope."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    @staticmethod
    def _ensure_windows() -> None:
        if sys.platform != "win32":
            raise KeyProtectionError("DPAPI_CURRENT_USER_UNAVAILABLE")

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(value)
        blob = _DataBlob(
            len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        )
        return blob, buffer

    def protect(self, value: bytes) -> bytes:
        self._ensure_windows()
        source, keepalive = self._blob(value)
        output = _DataBlob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = (
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        )
        crypt32.CryptProtectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "Titanium CommandDeck session bootstrap",
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        del keepalive
        if not ok:
            raise KeyProtectionError(f"DPAPI_PROTECT_FAILED:{ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))

    def unprotect(self, value: bytes) -> bytes:
        self._ensure_windows()
        source, keepalive = self._blob(value)
        output = _DataBlob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptUnprotectData.argtypes = (
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        )
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        del keepalive
        if not ok:
            raise KeyProtectionError(f"DPAPI_UNPROTECT_FAILED:{ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _current_user_sid() -> str:
    if sys.platform != "win32":
        raise KeyProtectionError("WINDOWS_ACL_UNAVAILABLE")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    token_query = 0x0008
    token_user = 1
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise KeyProtectionError(f"OPEN_PROCESS_TOKEN_FAILED:{ctypes.get_last_error()}")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, token_user, None, 0, ctypes.byref(size))
        if not size.value:
            raise KeyProtectionError(
                f"TOKEN_INFORMATION_SIZE_FAILED:{ctypes.get_last_error()}"
            )
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, token_user, buffer, size, ctypes.byref(size)
        ):
            raise KeyProtectionError(
                f"TOKEN_INFORMATION_FAILED:{ctypes.get_last_error()}"
            )
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_string = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_string)):
            raise KeyProtectionError(f"SID_STRING_FAILED:{ctypes.get_last_error()}")
        try:
            return sid_string.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _restrict_acl_to_current_user_and_system(path: Path) -> None:
    """Replace inheritance with a protected DACL containing user and SYSTEM only."""

    if sys.platform != "win32":
        raise KeyProtectionError("WINDOWS_ACL_UNAVAILABLE")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.SetFileSecurityW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    advapi32.SetFileSecurityW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    sid = _current_user_sid()
    descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;{sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise KeyProtectionError(f"SDDL_CONVERSION_FAILED:{ctypes.get_last_error()}")
    try:
        dacl_security_information = 0x00000004
        if not advapi32.SetFileSecurityW(
            str(path), dacl_security_information, descriptor
        ):
            raise KeyProtectionError(f"SET_FILE_ACL_FAILED:{ctypes.get_last_error()}")
    finally:
        kernel32.LocalFree(descriptor)


def current_user_sid() -> str:
    """Return the effective Windows account SID or fail closed."""

    return _current_user_sid()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_key_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise KeyProtectionError("LOCALAPPDATA_UNAVAILABLE")
    return (
        Path(local_app_data)
        / "Titanium"
        / "CommandDeck"
        / "session.key.dpapi"
    )


class WindowsAttestation:
    """Issue SID-bound HMAC challenges backed by a DPAPI-protected key."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        ttl_seconds: int = 30,
        key_path: Path | None = None,
        protector: KeyProtector | None = None,
        acl_hardener: Callable[[Path], None] = _restrict_acl_to_current_user_and_system,
        max_challenges: int = 1024,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        if not isinstance(max_challenges, int) or max_challenges <= 0:
            raise ValueError("max_challenges must be a positive integer")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._key_path = Path(key_path) if key_path is not None else _default_key_path()
        self._protector = protector or DpapiCurrentUserProtector()
        self._acl_hardener = acl_hardener
        self._max_challenges = max_challenges
        self._lock = threading.RLock()
        self._challenges: dict[str, datetime] = {}
        self._key = self._load_or_create_key()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _harden(self, path: Path) -> None:
        try:
            self._acl_hardener(path)
        except KeyProtectionError:
            raise
        except Exception as exc:
            raise KeyProtectionError("ACL_HARDENING_FAILED") from exc

    def _load_or_create_key(self) -> bytes:
        try:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            self._harden(self._key_path.parent)
            if self._key_path.exists():
                self._harden(self._key_path)
                key = self._protector.unprotect(self._key_path.read_bytes())
            else:
                key = secrets.token_bytes(32)
                protected = self._protector.protect(key)
                if not protected:
                    raise KeyProtectionError("EMPTY_PROTECTED_KEY")
                temporary = self._key_path.with_name(
                    f".{self._key_path.name}.{secrets.token_hex(8)}.tmp"
                )
                try:
                    with temporary.open("xb") as stream:
                        stream.write(protected)
                        stream.flush()
                        os.fsync(stream.fileno())
                    self._harden(temporary)
                    os.replace(temporary, self._key_path)
                    self._harden(self._key_path)
                finally:
                    temporary.unlink(missing_ok=True)
            if len(key) != 32:
                raise KeyProtectionError("INVALID_BOOTSTRAP_KEY")
            return key
        except KeyProtectionError:
            raise
        except Exception as exc:
            raise KeyProtectionError("KEY_PROTECTION_FAILED") from exc

    def challenge(self) -> str:
        now = self._now()
        with self._lock:
            self._purge_expired(now)
            if len(self._challenges) >= self._max_challenges:
                raise ChallengeCapacityExceeded("CHALLENGE_CAPACITY_EXCEEDED")
            while True:
                nonce = secrets.token_urlsafe(32)
                if nonce not in self._challenges:
                    break
            self._challenges[nonce] = now + timedelta(seconds=self._ttl_seconds)
        return nonce

    def _purge_expired(
        self, now: datetime, *, preserve_nonce: str | None = None
    ) -> None:
        expired = [
            nonce
            for nonce, expires_at in self._challenges.items()
            if nonce != preserve_nonce and now >= expires_at
        ]
        for nonce in expired:
            del self._challenges[nonce]

    def _message(self, sid: str, nonce: str, expires_at: datetime) -> bytes:
        return f"{sid}|{nonce}|{expires_at.isoformat()}".encode("utf-8")

    def test_proof(self, sid: str, nonce: str) -> str:
        """Create the native-host proof for an outstanding challenge."""

        now = self._now()
        with self._lock:
            self._purge_expired(now, preserve_nonce=nonce)
            expires_at = self._challenges.get(nonce)
            if expires_at is None:
                raise ReplayRejected("NONCE_REPLAYED")
            if now >= expires_at:
                del self._challenges[nonce]
                raise ChallengeExpired("NONCE_EXPIRED")
            return hmac.new(
                self._key,
                self._message(sid, nonce, expires_at),
                hashlib.sha256,
            ).hexdigest()

    def verify(self, sid: str, nonce: str, proof: str) -> None:
        now = self._now()
        with self._lock:
            self._purge_expired(now, preserve_nonce=nonce)
            expires_at = self._challenges.pop(nonce, None)
            if expires_at is None:
                raise ReplayRejected("NONCE_REPLAYED")
            if now >= expires_at:
                raise ChallengeExpired("NONCE_EXPIRED")
            expected = hmac.new(
                self._key,
                self._message(sid, nonce, expires_at),
                hashlib.sha256,
            ).hexdigest()
            if not isinstance(proof, str) or not hmac.compare_digest(expected, proof):
                raise ProofRejected("WINDOWS_PROOF_REJECTED")
