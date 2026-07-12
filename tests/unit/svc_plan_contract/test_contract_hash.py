"""compute_contract_hash — deterministic, content-addressed, sha256_ref-shaped."""

from __future__ import annotations

import re

from saena_plan_contract.contract_hash import compute_contract_hash

_SHA256_REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def test_same_content_same_hash() -> None:
    plan = {"a": 1, "b": [1, 2, 3]}
    assert compute_contract_hash(plan) == compute_contract_hash(dict(plan))


def test_key_order_does_not_affect_hash() -> None:
    plan_a = {"a": 1, "b": 2}
    plan_b = {"b": 2, "a": 1}
    assert compute_contract_hash(plan_a) == compute_contract_hash(plan_b)


def test_different_content_different_hash() -> None:
    plan_a = {"a": 1}
    plan_b = {"a": 2}
    assert compute_contract_hash(plan_a) != compute_contract_hash(plan_b)


def test_hash_matches_sha256_ref_pattern() -> None:
    digest = compute_contract_hash({"x": "y"})
    assert _SHA256_REF_PATTERN.match(digest)
