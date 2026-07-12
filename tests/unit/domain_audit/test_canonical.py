"""Determinism tests for saena_domain.audit.canonical."""

from __future__ import annotations

import hashlib

from saena_domain.audit.canonical import canonical_json, sha256_hex


def test_canonical_json_sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_is_compact() -> None:
    out = canonical_json({"a": 1, "b": [1, 2]})
    assert " " not in out
    assert out == '{"a":1,"b":[1,2]}'


def test_canonical_json_deterministic_across_calls() -> None:
    obj = {"nested": {"z": 1, "y": [3, 2, 1], "a": None}, "top": "value"}
    first = canonical_json(obj)
    for _ in range(50):
        assert canonical_json(obj) == first


def test_canonical_json_nested_key_order_independent() -> None:
    left = {"outer": {"z": 1, "a": 2}, "list": [{"b": 1, "a": 2}]}
    right = {"list": [{"a": 2, "b": 1}], "outer": {"a": 2, "z": 1}}
    assert canonical_json(left) == canonical_json(right)


def test_canonical_json_distinguishes_different_values() -> None:
    assert canonical_json({"a": 1}) != canonical_json({"a": 2})


def test_sha256_hex_deterministic() -> None:
    text = canonical_json({"x": 1})
    assert sha256_hex(text) == sha256_hex(text)


def test_sha256_hex_is_64_lowercase_hex_chars() -> None:
    digest = sha256_hex("hello world")
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256_hex_known_vector() -> None:
    # Standard SHA-256("") vector — pins the hashing primitive itself.
    assert sha256_hex("") == hashlib.sha256(b"").hexdigest()
