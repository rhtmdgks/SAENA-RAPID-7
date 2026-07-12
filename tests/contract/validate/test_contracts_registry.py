"""registry.json self-validation + relational checks (w1-11 harness consumer).

`registry.schema.json`'s own $comment states the relational constraints it
cannot express are "enforced by tests/contract/validate/test_registry.py (W1
harness)" -- this module is that promised consumer, named
`test_contracts_registry.py` rather than `test_registry.py` verbatim to
avoid a pytest module-basename collision with the pre-existing
`packages/observability/tests/test_registry.py` (both directories lack
`__init__.py` by design, so pytest's rootdir-based module naming cannot
disambiguate two same-named `test_registry.py` files -- confirmed via
`uv run just verify` failing with `import file mismatch` before this
rename; renaming this w1-11-owned file was the only in-scope fix, since
`packages/observability/**` is outside this unit's exclusive path). All
judgment functions (`check_name_major_unique`, etc.) live in
`harness.registry` (w1-10, single implementation, tests/contract/README.md
ownership split); this module only calls them and asserts on their output.

Registry currently has 26 active entries (Wave 1 first release). This
module is parametrize-ready: `iter_entries()` drives every per-entry
assertion against the live registry.
"""

from __future__ import annotations

import sys

import pytest
from harness import registry as registry_mod


def test_registry_document_validates_against_schema() -> None:
    """registry.json must validate against registry.schema.json (jsonschema.validate)."""
    registry_mod.validate_registry_document()


def test_registry_version_is_1() -> None:
    document = registry_mod.load_registry_raw()
    assert document["registry_version"] == 1


def test_load_registry_returns_typed_entries() -> None:
    entries = registry_mod.load_registry()
    assert isinstance(entries, list)


def test_registry_populated_state_invariants() -> None:
    """w1-15: registry carries all hand-authored contracts. Every relational
    check must run clean on the REAL entry list (no longer vacuous)."""
    entries = registry_mod.load_registry()
    assert len(entries) == 26
    closed = {e.name for e in entries if e.compat_class == "closed"}
    assert {"change-plan", "approval-decision"} <= closed
    assert all((not e.signed) or e.compat_class == "closed" for e in entries)
    frozen = [e for e in entries if e.compat_class == "frozen"]
    assert [e.name for e in frozen] == ["event-envelope"]
    assert frozen[0].frozen_authority_adr == "ADR-0013"
    runctx = [e for e in entries if e.catalog_name == "RunContext"]
    assert len(runctx) == 2, "R10 split back-reference"


@pytest.mark.parametrize(
    "check_fn",
    [
        registry_mod.check_name_major_unique,
        registry_mod.check_full_version_major_prefix,
        registry_mod.check_id_category_and_path,
        registry_mod.check_schema_file_exists,
    ],
    ids=[
        "name_major_unique",
        "full_version_major_prefix",
        "id_category_and_path",
        "schema_file_exists",
    ],
)
def test_relational_check_runs_clean_on_empty_registry(check_fn) -> None:  # type: ignore[no-untyped-def]
    """Each individual relational check function runs without raising and
    returns no violations against the current (populated) entry list --
    parametrize-ready: once entries exist, `iter_entries()` below feeds real
    data through the exact same function objects.
    """
    entries = registry_mod.iter_entries()
    violations = check_fn(entries)
    assert violations == []


def test_all_relational_violations_empty_on_empty_registry() -> None:
    entries = registry_mod.iter_entries()
    violations = registry_mod.all_relational_violations(entries)
    assert violations == []


# --------------------------------------------------------------------------
# Meta-tests: prove the relational check functions actually detect
# violations on synthetic data (not just vacuously pass on an empty list).
# --------------------------------------------------------------------------


def _make_entry(**overrides: object) -> registry_mod.RegistryEntry:
    base: dict[str, object] = {
        "name": "tenant-context",
        "catalog_name": "TenantContext",
        "category": "context",
        "compat_class": "closed",
        "signed": False,
        "format": "json-schema",
        "major": 1,
        "full_version": "1.0.0",
        "$id": "https://schemas.the-saena.ai/context/tenant-context/v1/tenant-context.schema.json",
        "owner": "contracts-steward",
        "status": "active",
    }
    base.update(overrides)
    return registry_mod.RegistryEntry.from_dict(base)


def test_check_name_major_unique_detects_duplicate() -> None:
    entries = [_make_entry(), _make_entry()]
    violations = registry_mod.check_name_major_unique(entries)
    assert violations, "expected a duplicate name+major violation but got none"
    assert "tenant-context" in violations[0]


def test_check_full_version_major_prefix_detects_mismatch() -> None:
    entries = [_make_entry(major=2, full_version="1.0.0")]
    violations = registry_mod.check_full_version_major_prefix(entries)
    assert violations, "expected a major-prefix mismatch violation but got none"


def test_check_id_category_and_path_detects_category_mismatch() -> None:
    entries = [_make_entry(category="domain")]
    violations = registry_mod.check_id_category_and_path(entries)
    assert violations, "expected a category-segment mismatch violation but got none"
    assert "category" in violations[0]


def test_check_id_category_and_path_detects_bad_id_pattern() -> None:
    entries = [_make_entry(**{"$id": "https://example.com/not-the-right-scheme"})]
    violations = registry_mod.check_id_category_and_path(entries)
    assert violations, "expected an $id pattern-mismatch violation but got none"


def test_check_schema_file_exists_detects_missing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    entries = [_make_entry(name="does-not-exist-contract")]
    violations = registry_mod.check_schema_file_exists(entries, contracts_dir=tmp_path)
    assert violations, "expected a missing-schema-file violation but got none"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
