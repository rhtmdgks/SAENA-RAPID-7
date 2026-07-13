"""Tests for saena_domain.audit.hashing (compute_entry_hash, GENESIS)."""

from __future__ import annotations

import re

from saena_domain.audit.hashing import GENESIS, compute_entry_hash

_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def test_genesis_is_none() -> None:
    assert GENESIS is None


def test_compute_entry_hash_matches_sha256_ref_wire_form() -> None:
    result = compute_entry_hash({"action": "a.b.c.v1"}, GENESIS)
    assert _SHA256_REF_RE.match(result)


def test_compute_entry_hash_deterministic() -> None:
    entry = {"action": "a.b.c.v1", "payload": {"z": 1, "a": 2}}
    first = compute_entry_hash(entry, "sha256:" + "0" * 64)
    for _ in range(20):
        assert compute_entry_hash(entry, "sha256:" + "0" * 64) == first


def test_compute_entry_hash_sensitive_to_prev_hash() -> None:
    entry = {"action": "a.b.c.v1"}
    hash_genesis = compute_entry_hash(entry, GENESIS)
    hash_with_prev = compute_entry_hash(entry, "sha256:" + "1" * 64)
    assert hash_genesis != hash_with_prev


def test_compute_entry_hash_sensitive_to_entry_content() -> None:
    hash_a = compute_entry_hash({"action": "a.b.c.v1"}, GENESIS)
    hash_b = compute_entry_hash({"action": "x.y.z.v1"}, GENESIS)
    assert hash_a != hash_b


def test_compute_entry_hash_key_order_independent() -> None:
    left = compute_entry_hash({"b": 1, "a": 2}, GENESIS)
    right = compute_entry_hash({"a": 2, "b": 1}, GENESIS)
    assert left == right
