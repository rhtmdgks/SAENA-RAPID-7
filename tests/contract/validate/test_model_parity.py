"""Schema-vs-pydantic model parity (w1-11, approved plan §2 deliverable 2
"model parity").

For every contract fixture in `_model_registry.BINDINGS` /
`EVENT_PAYLOAD_BINDINGS`: the jsonschema+referencing validator verdict
(equivalent to check-jsonschema per test_envelope_fixtures.py's own
documented rationale -- the CLI subprocess form cannot resolve this
catalog's cross-file $refs) must agree with the saena_schemas pydantic
model's `.model_validate()` verdict:

  - valid fixture  => BOTH accept.
  - invalid fixture => BOTH reject, UNLESS the fixture name is listed in
    the binding's `known_conditional_gaps` (a documented codegen-coverage
    gap: JSON Schema allOf/if-then conditionals are not translated into
    pydantic-enforced validators by the current codegen flag set,
    justfile `codegen` recipe -- the schema is authoritative, ADR-0011
    SSOT, and the divergence is asserted explicitly rather than silently
    ignored).
  - gap fixture (schema-valid by design, e.g. namespace-mismatch,
    payload-with-secret, tenant-id-in-payload) => BOTH accept (neither
    side can express the cross-field/semantic invariant the fixture
    documents).

Models are imported from saena_schemas (packages/schemas, w1-12 scope,
codegen-only, consumed read-only here per packages/schemas/README.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _model_registry import BINDINGS, EVENT_PAYLOAD_BINDINGS, ContractBinding
from _support import fixture_pairs, load_json, strip_metadata
from pydantic import ValidationError

ALL_BINDINGS: dict[str, ContractBinding] = {**BINDINGS, **EVENT_PAYLOAD_BINDINGS}

# Gap-fixture names are contract-scoped; collected here so the parity
# test can treat them as a third bucket (both-accept) distinct from
# ordinary invalid fixtures (both-reject) and known conditional gaps
# (schema-rejects/pydantic-accepts).
_GAP_FIXTURE_NAMES_BY_CONTRACT: dict[str, frozenset[str]] = {
    "tenant-context": frozenset({"namespace-mismatch.json"}),
    "audit-event": frozenset({"payload-credential-like-value.json"}),
    "patch-unit-completed": frozenset({"tenant-id-in-payload-gap.json"}),
}


def _schema_accepts(binding: ContractBinding, data: dict) -> bool:
    validator = binding.build_validator()
    return not list(validator.iter_errors(data))


def _pydantic_accepts(binding: ContractBinding, data: dict) -> bool:
    try:
        binding.model_cls.model_validate(data)
    except ValidationError:
        return False
    return True


def _valid_params() -> list[pytest.param]:  # type: ignore[type-arg]
    params = []
    for name, binding in ALL_BINDINGS.items():
        for path in fixture_pairs(binding.fixture_dir / "valid"):
            params.append(pytest.param(name, path, id=f"{name}/{path.name}"))
    return params


def _invalid_params() -> list[pytest.param]:  # type: ignore[type-arg]
    """(name, path, is_known_gap) for every invalid/ fixture, EXCLUDING
    schema-valid gap fixtures (handled by `_gap_params` instead).
    """
    params = []
    for name, binding in ALL_BINDINGS.items():
        gap_names = _GAP_FIXTURE_NAMES_BY_CONTRACT.get(name, frozenset())
        for path in fixture_pairs(binding.fixture_dir / "invalid"):
            if path.name in gap_names:
                continue
            params.append(pytest.param(name, path, id=f"{name}/{path.name}"))
    return params


def _gap_params() -> list[pytest.param]:  # type: ignore[type-arg]
    params = []
    for name, gap_names in _GAP_FIXTURE_NAMES_BY_CONTRACT.items():
        binding = ALL_BINDINGS[name]
        for path in fixture_pairs(binding.fixture_dir / "invalid"):
            if path.name in gap_names:
                params.append(pytest.param(name, path, id=f"{name}/{path.name}"))
    return params


@pytest.mark.parametrize(("name", "fixture_path"), _valid_params())
def test_valid_fixture_both_sides_accept(name: str, fixture_path: Path) -> None:
    binding = ALL_BINDINGS[name]
    data = strip_metadata(load_json(fixture_path))
    schema_ok = _schema_accepts(binding, data)
    pydantic_ok = _pydantic_accepts(binding, data)
    assert schema_ok, (
        f"{name}/{fixture_path.name}: schema validator unexpectedly rejected a valid fixture"
    )
    assert pydantic_ok, (
        f"{name}/{fixture_path.name}: pydantic model {binding.model_cls.__name__} unexpectedly "
        "rejected a schema-valid fixture -- codegen/schema drift, not a documented conditional gap"
    )


@pytest.mark.parametrize(("name", "fixture_path"), _invalid_params())
def test_invalid_fixture_parity_or_documented_gap(name: str, fixture_path: Path) -> None:
    binding = ALL_BINDINGS[name]
    data = strip_metadata(load_json(fixture_path))
    schema_ok = _schema_accepts(binding, data)
    pydantic_ok = _pydantic_accepts(binding, data)

    assert not schema_ok, (
        f"{name}/{fixture_path.name}: schema validator unexpectedly accepted an invalid fixture"
    )

    if fixture_path.name in binding.known_conditional_gaps:
        # Documented codegen-coverage gap: schema rejects (allOf/if-then
        # conditional), pydantic model has no equivalent validator and
        # accepts. Assert the DIVERGENCE explicitly so this stays a
        # tracked, proven fact rather than a silently-passing assumption.
        assert pydantic_ok, (
            f"{name}/{fixture_path.name}: expected the DOCUMENTED conditional gap (pydantic "
            "accepts what the schema's allOf/if-then rejects) but pydantic also rejected -- "
            "the gap may have closed (codegen improved); if so, remove this fixture from "
            "known_conditional_gaps in _model_registry.py rather than leaving a stale entry"
        )
    else:
        assert not pydantic_ok, (
            f"{name}/{fixture_path.name}: pydantic model {binding.model_cls.__name__} "
            "unexpectedly ACCEPTED a fixture the schema rejects, and this fixture is not "
            "listed in known_conditional_gaps -- either add it there with a documented "
            "reason, or this is a genuine codegen/schema drift bug"
        )


@pytest.mark.parametrize(("name", "fixture_path"), _gap_params())
def test_gap_fixture_both_sides_accept(name: str, fixture_path: Path) -> None:
    """Gap fixtures (schema-valid by design -- namespace-mismatch,
    payload-with-secret, tenant-id-in-payload-gap) must be accepted by
    BOTH the schema validator and the pydantic model, since neither
    representation can express the cross-field/semantic invariant the
    fixture documents.
    """
    binding = ALL_BINDINGS[name]
    raw = load_json(fixture_path)
    assert raw.get("_note"), f"{name}/{fixture_path.name}: gap fixture must carry a _note field"
    data = strip_metadata(raw)
    schema_ok = _schema_accepts(binding, data)
    pydantic_ok = _pydantic_accepts(binding, data)
    assert schema_ok, f"{name}/{fixture_path.name}: expected the gap fixture to be schema-valid"
    assert pydantic_ok, (
        f"{name}/{fixture_path.name}: expected the gap fixture to also be pydantic-valid "
        f"({binding.model_cls.__name__})"
    )


def test_gap_fixture_coverage_matches_known_gap_fixtures() -> None:
    """Meta-test: every contract with a documented gap fixture in
    _GAP_FIXTURE_NAMES_BY_CONTRACT actually has that fixture on disk --
    prevents a stale registry entry silently no-op'ing.
    """
    for name, gap_names in _GAP_FIXTURE_NAMES_BY_CONTRACT.items():
        binding = ALL_BINDINGS[name]
        on_disk = {p.name for p in fixture_pairs(binding.fixture_dir / "invalid")}
        missing = gap_names - on_disk
        assert not missing, (
            f"{name}: gap fixture(s) {missing} not found under {binding.fixture_dir}/invalid"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
