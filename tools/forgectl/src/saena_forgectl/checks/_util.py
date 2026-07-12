"""Internal helpers shared by check modules — not part of the public API."""

from __future__ import annotations

from typing import Any


def get_path(values: dict[str, Any], *keys: str) -> Any:
    """Walk a dotted key path through nested mappings, returning `None` if
    any segment is absent or not itself a mapping (fail-soft *lookup* —
    each check decides for itself whether an absent value means "declared
    absent" -> fail, since §8.1's conditions are all "X is absent" checks
    where absence is the failure signal, not a shrug)."""
    current: Any = values
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
