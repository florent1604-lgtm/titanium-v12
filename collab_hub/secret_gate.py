"""Small, deterministic secret detector used before CollabHub persistence."""

from __future__ import annotations

import re


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "BEARER_TOKEN",
        re.compile(r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    ),
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
    ),
)


def scan_text(value: str) -> tuple[str, ...]:
    """Return stable reason codes for secret material found in ``value``."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return tuple(reason for reason, pattern in _SECRET_PATTERNS if pattern.search(value))
