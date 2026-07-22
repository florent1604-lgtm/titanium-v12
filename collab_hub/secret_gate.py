"""Small, deterministic secret detector used before CollabHub persistence."""

from __future__ import annotations

import re


_ASSIGNED_SECRET = (
    r"(?!(?:['\"])?(?:none|null|redacted|masked|<redacted>|\[redacted\]|\*+|"
    r"\$\{[A-Z][A-Z0-9_]*\})(?:['\"])?\s*(?:[,;}\]]|$))"
    r"(?:\"[^\"\r\n]{4,}\"|'[^'\r\n]{4,}'|[^\s,;]{4,})"
)

_AUTHORIZATION_BEARER = re.compile(
    r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE
)
_FREE_BEARER = re.compile(r"\bbearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
    ),
    (
        "PASSWORD",
        re.compile(
            rf"(?<![A-Za-z0-9_])['\"]?(?:password|passwd|pwd)['\"]?"
            rf"\s*[:=]\s*{_ASSIGNED_SECRET}",
            re.IGNORECASE,
        ),
    ),
    (
        "TOKEN",
        re.compile(
            rf"(?<![A-Za-z0-9_])['\"]?"
            rf"(?:access[_-]?token|refresh[_-]?token|token)['\"]?"
            rf"\s*[:=]\s*{_ASSIGNED_SECRET}",
            re.IGNORECASE,
        ),
    ),
    (
        "API_KEY",
        re.compile(
            rf"(?<![A-Za-z0-9_])['\"]?api[_-]?key['\"]?"
            rf"\s*[:=]\s*{_ASSIGNED_SECRET}",
            re.IGNORECASE,
        ),
    ),
)


def _looks_like_token(candidate: str) -> bool:
    if len(candidate) < 20:
        return False
    segments = candidate.split(".")
    if len(segments) >= 3 and all(len(segment) >= 4 for segment in segments):
        return True
    if len(candidate) >= 32 and re.fullmatch(r"[A-Fa-f0-9]+", candidate):
        return True
    uppercase = sum(char.isupper() for char in candidate)
    lowercase = sum(char.islower() for char in candidate)
    digits = sum(char.isdigit() for char in candidate)
    diverse = len(set(candidate)) >= 10
    return diverse and (
        (
            uppercase > 0
            and lowercase > 0
            and digits > 0
            and any(char in "._~+/=" for char in candidate)
        )
        or (len(candidate) >= 24 and uppercase >= 4 and lowercase >= 4 and digits >= 4)
    )


def _has_bearer_token(value: str) -> bool:
    if _AUTHORIZATION_BEARER.search(value):
        return True
    return any(_looks_like_token(match.group(1)) for match in _FREE_BEARER.finditer(value))


def scan_text(value: str) -> tuple[str, ...]:
    """Return stable reason codes for secret material found in ``value``."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    reasons = ["BEARER_TOKEN"] if _has_bearer_token(value) else []
    reasons.extend(
        reason for reason, pattern in _SECRET_PATTERNS if pattern.search(value)
    )
    return tuple(reasons)
