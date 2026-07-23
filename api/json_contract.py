"""Pure helpers for case-insensitive-safe public JSON contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def serialize_signal_states(
    states: Mapping[str, Mapping[str, Any]],
    criteria_names: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Separate boolean scoring criteria from same-named measurements.

    The live scoring context intentionally carries both lowercase measurements
    and uppercase criterion flags. Keeping them flat is valid JSON but breaks
    case-insensitive clients. This function changes only the public projection
    and never mutates the live signal state.
    """
    criterion_keys = frozenset(criteria_names)
    result: dict[str, dict[str, Any]] = {}
    for symbol, state in states.items():
        projected = {
            key: value for key, value in state.items()
            if key not in criterion_keys
        }
        criteria = {
            key: value for key, value in state.items()
            if key in criterion_keys
        }
        if criteria:
            projected["criteria"] = criteria
        result[symbol] = projected
    return result
