"""Values-file loading — YAML parsing with a clean, named error surface.

k3s spec §7's values skeleton (`global.engineScope`,
`global.policyBundle.digest`, `global.network.defaultDeny`, ...) is a plain
nested mapping; `load_values` returns exactly that (`dict[str, Any]`) with
no schema coercion. Each check module reads the specific sub-keys it needs
directly and treats an absent key as "not declared" (fail-closed per
check, documented on each check function).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from saena_forgectl.errors import ValuesFileError


def load_values(path: str | Path) -> dict[str, Any]:
    """Load and parse a Helm values YAML file into a plain mapping.

    Raises `ValuesFileError` (never a bare `yaml.YAMLError`/`OSError`/
    `AttributeError`) if the path does not exist, is unreadable, contains
    invalid YAML, or parses to a non-mapping top level (including an empty
    file, which YAML parses to `None`).
    """
    values_path = Path(path)
    try:
        raw_text = values_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValuesFileError(str(values_path), f"could not read file: {exc}") from exc

    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValuesFileError(str(values_path), f"invalid YAML: {exc}") from exc

    if not isinstance(document, dict):
        actual_type = type(document).__name__
        raise ValuesFileError(
            str(values_path),
            f"top-level YAML document must be a mapping, got {actual_type}",
        )

    return document
