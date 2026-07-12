"""Canonical JSON serialization and SHA-256 hex digest helpers.

The hash chain (`hashing.py`) and lineage ref (`lineage.py`) both depend on a
single deterministic byte representation of a Python object. `canonical_json`
is that representation: sorted keys (recursively, via `json.dumps`'s
`sort_keys`), compact separators (no whitespace padding), UTF-8 text. Given
the same logical object, `canonical_json` returns the identical string on
every run/process/machine — this determinism is asserted by
`tests/unit/domain_audit/test_canonical.py`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_SEPARATORS = (",", ":")


def canonical_json(obj: Any) -> str:
    """Serialize `obj` to a deterministic compact JSON string.

    Sorted keys + compact separators + UTF-8-safe text output (non-ASCII
    characters are escaped by default, which keeps the output ASCII-only and
    avoids encoding ambiguity across platforms). Numbers, `None`/`null`,
    `bool`, sequences, and nested mappings are all supported via the
    standard-library `json` encoder — the caller is responsible for passing
    only JSON-serializable data (audit payloads are always JSON-shaped per
    the `AuditEvent` contract's `payload: object` field).
    """
    return json.dumps(obj, sort_keys=True, separators=_SEPARATORS, ensure_ascii=True)


def sha256_hex(text: str) -> str:
    """Return the lowercase hex SHA-256 digest of `text` (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
