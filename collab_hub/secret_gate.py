"""Small, deterministic secret detector used before CollabHub persistence."""

from __future__ import annotations

import re


_ASSIGNED_SECRET = (
    r"(?!(?:['\"])?(?:none|null|redacted|masked|<redacted>|\*+|"
    r"\$\{[A-Z][A-Z0-9_]*\})(?:['\"])?(?:\s|[,;]|$))"
    r"(?:\"[^\"\r\n]{4,}\"|'[^'\r\n]{4,}'|[^\s,;]{4,})"
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "BEARER_TOKEN",
        re.compile(
            r"(?:\bauthorization\s*:\s*bearer\s+\S+|"
            r"\bbearer\s+(?!(?:authentication|token|redacted|none|null)\b)"
            r"[A-Za-z0-9._~+/=-]{8,})",
            re.IGNORECASE,
        ),
    ),
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
    ),
    (
        "PASSWORD",
        re.compile(rf"\b(?:password|passwd|pwd)\s*[:=]\s*{_ASSIGNED_SECRET}", re.IGNORECASE),
    ),
    (
        "TOKEN",
        re.compile(
            rf"\b(?:access[_-]?token|refresh[_-]?token|token)\s*[:=]\s*"
            rf"{_ASSIGNED_SECRET}",
            re.IGNORECASE,
        ),
    ),
    (
        "API_KEY",
        re.compile(rf"\bapi[_-]?key\s*[:=]\s*{_ASSIGNED_SECRET}", re.IGNORECASE),
    ),
)


def scan_text(value: str) -> tuple[str, ...]:
    """Return stable reason codes for secret material found in ``value``."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return tuple(reason for reason, pattern in _SECRET_PATTERNS if pattern.search(value))
