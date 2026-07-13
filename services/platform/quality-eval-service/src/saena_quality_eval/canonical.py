"""Thin re-export of `saena_domain.audit.canonical` — the deterministic
byte-representation helper this package's determinism tests (mission item 8)
and idempotency tests (mission item 11) compare `VerificationResult`/event
payload dicts through. No new logic: `saena_domain.audit.canonical_json`
already IS the repo's single canonical-JSON implementation (sorted keys,
compact separators, ASCII-safe) and this package reuses it verbatim rather
than defining a second one.
"""

from __future__ import annotations

from saena_domain.audit.canonical import canonical_json, sha256_hex

__all__ = ["canonical_json", "sha256_hex"]
