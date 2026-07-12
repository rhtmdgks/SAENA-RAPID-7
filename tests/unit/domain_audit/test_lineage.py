"""Tests for saena_domain.audit.lineage (make_lineage_ref, is_lineage_ref)."""

from __future__ import annotations

import pytest
from saena_domain.audit.lineage import is_lineage_ref, make_lineage_ref

VALID_SHA256_REF = "sha256:" + "a" * 64


def test_make_lineage_ref_wraps_sha256_ref() -> None:
    assert make_lineage_ref(VALID_SHA256_REF) == f"audit:{VALID_SHA256_REF}"


def test_make_lineage_ref_matches_adr_0013_example_shape() -> None:
    # ADR-0013 appendix example: "sha256:8f2e1c9a...". Confirm our wrapped
    # form is that value prefixed with the audit: scheme.
    example = "sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e"
    assert make_lineage_ref(example) == f"audit:{example}"


def test_make_lineage_ref_rejects_malformed_hash() -> None:
    with pytest.raises(ValueError, match="sha256_ref"):
        make_lineage_ref("not-a-valid-hash")


def test_make_lineage_ref_rejects_bare_hex_without_prefix() -> None:
    with pytest.raises(ValueError, match="sha256_ref"):
        make_lineage_ref("a" * 64)


def test_make_lineage_ref_rejects_wrong_length_hex() -> None:
    with pytest.raises(ValueError, match="sha256_ref"):
        make_lineage_ref("sha256:" + "a" * 63)


def test_is_lineage_ref_true_for_well_formed_ref() -> None:
    ref = make_lineage_ref(VALID_SHA256_REF)
    assert is_lineage_ref(ref) is True


def test_is_lineage_ref_false_for_bare_sha256_ref() -> None:
    # A bare sha256_ref (no audit: scheme) is a different contract's key
    # (e.g. SourceSnapshot content hash) — must not be confused with a
    # lineage ref.
    assert is_lineage_ref(VALID_SHA256_REF) is False


def test_is_lineage_ref_false_for_garbage() -> None:
    assert is_lineage_ref("not-a-ref") is False


def test_lineage_ref_is_deterministic() -> None:
    first = make_lineage_ref(VALID_SHA256_REF)
    for _ in range(10):
        assert make_lineage_ref(VALID_SHA256_REF) == first
