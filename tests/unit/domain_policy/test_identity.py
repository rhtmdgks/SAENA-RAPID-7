"""canonical_actor_id — NFKC + strip + casefold (critic MUST-FIX 2)."""

from __future__ import annotations

from saena_domain.policy.identity import canonical_actor_id


def test_case_variants_canonicalize_to_same_value() -> None:
    assert canonical_actor_id("Actor-1") == canonical_actor_id("actor-1")
    assert canonical_actor_id("ACTOR-1") == canonical_actor_id("actor-1")


def test_whitespace_variants_canonicalize_to_same_value() -> None:
    assert canonical_actor_id(" actor-1") == canonical_actor_id("actor-1")
    assert canonical_actor_id("actor-1 ") == canonical_actor_id("actor-1")
    assert canonical_actor_id("  actor-1  ") == canonical_actor_id("actor-1")


def test_combined_case_and_whitespace_variants_canonicalize_to_same_value() -> None:
    assert canonical_actor_id("  Actor-1  ") == canonical_actor_id("actor-1")


def test_distinct_identities_remain_distinct() -> None:
    assert canonical_actor_id("actor-1") != canonical_actor_id("actor-2")


def test_unicode_compatibility_forms_fold_together() -> None:
    # NFKC folds compatibility-equivalent forms (e.g. full-width digits) to
    # their canonical ASCII-equivalent form.
    assert canonical_actor_id("actor１") == canonical_actor_id("actor1")
