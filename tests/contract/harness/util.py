"""Fixture-metadata stripping + tempfile helpers.

Promoted from `_strip_metadata_to_tempfile()` in
`tests/contract/test_envelope_fixtures.py` (tests/contract/README.md
"Fixture metadata convention" -- that file stays owned by w1-05/envelope
and is NOT edited here; this module is the shared, harness-owned copy of
the pattern for use by tests/contract/compat/**).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Fixture-authoring metadata keys (tests/contract/README.md "Fixture
# metadata convention") that must never be treated as instance payload
# content when invoking a schema validator.
METADATA_KEYS: tuple[str, ...] = ("_expected_violation", "_note")


def strip_metadata(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `obj` with top-level metadata keys removed.

    Strips any top-level key starting with "_" (a superset of the two
    currently-documented keys, `_expected_violation`/`_note`, so future
    metadata keys following the same underscore-prefix convention are
    covered without requiring another harness edit).
    """
    return {key: value for key, value in obj.items() if not key.startswith("_")}


def write_stripped_to_tempfile(fixture_path: Path, tmp_dir: Path) -> Path:
    """Write a copy of `fixture_path` with metadata keys removed into `tmp_dir`.

    Returns the path to the written copy. Mirrors
    `_strip_metadata_to_tempfile()` in test_envelope_fixtures.py so that
    validator subprocess invocations (e.g. `check-jsonschema`) see only
    real instance payload content, never fixture-authoring annotations.
    """
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    stripped = strip_metadata(data)
    out_path = tmp_dir / fixture_path.name
    out_path.write_text(json.dumps(stripped), encoding="utf-8")
    return out_path
