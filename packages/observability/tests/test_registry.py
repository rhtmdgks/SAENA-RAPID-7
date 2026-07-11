"""Validation harness for the SAENA telemetry attribute registry (ADR-0016).

`packages/observability` is deliberately NOT a uv workspace member (no
pyproject.toml here — ADR-0016 W0 scope is conventions + registry only).
These tests are still collected because root pyproject.toml sets
`testpaths = ["packages"]`.

Registry data is authored in attributes.yaml (human-edited SSOT), but
PyYAML is not part of the reachable dependency surface for this package, so
attributes.json is maintained as a manually-synced generated mirror (see
the note at the top of attributes.yaml and in CONVENTIONS.md). These tests
validate the JSON mirror using stdlib `json` plus the `jsonschema` library,
which IS available in the workspace dev group (via check-jsonschema's
dependency closure / direct availability confirmed in this environment).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"
SCHEMA_PATH = REGISTRY_DIR / "attributes.schema.json"
ATTRIBUTES_JSON_PATH = REGISTRY_DIR / "attributes.json"
ATTRIBUTES_YAML_PATH = REGISTRY_DIR / "attributes.yaml"
REDACTION_RULES_PATH = REGISTRY_DIR / "redaction-rules.yaml"

CONTEXTS = ("tenant", "system", "aggregate")

# Attributes that ADR-0013's context_type table marks as forbidden
# (property-level removal) in AggregateContext. Any registry entry that does
# not mark aggregate=forbidden for these names is a rule-consistency
# violation regardless of what the schema alone would accept (the schema
# only constrains the *shape* of a contexts block, not this specific
# cross-attribute policy).
AGGREGATE_FORBIDDEN_IDENTIFIERS = ("saena.tenant_id", "saena.run_id")


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_attributes() -> list[dict[str, Any]]:
    with ATTRIBUTES_JSON_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def assert_tenant_run_id_forbidden_in_aggregate(entries: list[dict[str, Any]]) -> None:
    """Consistency check described in the task: tenant_id/run_id MUST be
    forbidden in aggregate context. Raises AssertionError (via pytest
    assert) naming every violating entry if the rule is broken.
    """
    violations = []
    for entry in entries:
        name = entry.get("name")
        if name in AGGREGATE_FORBIDDEN_IDENTIFIERS:
            rule = entry.get("contexts", {}).get("aggregate")
            if rule != "forbidden":
                violations.append((name, rule))
    assert not violations, (
        "V-AGG-TENANT consistency violation(s): the following identifying "
        f"attributes are not marked aggregate=forbidden: {violations}"
    )


class TestRegistryFilesExist:
    def test_schema_file_exists(self) -> None:
        assert SCHEMA_PATH.is_file()

    def test_attributes_yaml_exists(self) -> None:
        assert ATTRIBUTES_YAML_PATH.is_file()

    def test_attributes_json_mirror_exists(self) -> None:
        assert ATTRIBUTES_JSON_PATH.is_file()

    def test_redaction_rules_yaml_exists(self) -> None:
        assert REDACTION_RULES_PATH.is_file()


class TestSchemaIsValid2020_12:
    def test_schema_declares_2020_12(self) -> None:
        schema = load_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_id(self) -> None:
        schema = load_schema()
        assert schema["$id"] == (
            "https://schemas.the-saena.ai/common/observability-attribute-registry/"
            "v1/attributes.schema.json"
        )

    def test_schema_is_self_consistent_metaschema(self) -> None:
        # Equivalent in-process check to
        # `check-jsonschema --check-metaschema` (also run standalone in CI).
        schema = load_schema()
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)


class TestAttributesJsonValidatesAgainstSchema:
    def test_all_entries_validate(self) -> None:
        schema = load_schema()
        entries = load_attributes()
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(entries), key=lambda e: e.path)
        assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)

    def test_registry_is_nonempty(self) -> None:
        entries = load_attributes()
        assert len(entries) >= 8

    def test_all_names_match_namespace_pattern(self) -> None:
        entries = load_attributes()
        import re

        pattern = re.compile(r"^saena\.[a-z0-9_.]+$")
        for entry in entries:
            assert pattern.match(entry["name"]), entry["name"]

    def test_all_entries_declare_all_three_contexts(self) -> None:
        entries = load_attributes()
        for entry in entries:
            assert set(entry["contexts"].keys()) == set(CONTEXTS), entry["name"]


class TestPlantedViolationDetection:
    """Negative test: a fixture entry that WRONGLY marks aggregate=required
    for saena.tenant_id must be detected as a rule-consistency violation by
    assert_tenant_run_id_forbidden_in_aggregate (even though it may be
    schema-shape-valid, since the schema alone can't express this
    cross-attribute policy — that's exactly why this check exists as an
    explicit test, per ADR-0016's registry-lint intent)."""

    def test_real_registry_passes_consistency_check(self) -> None:
        entries = load_attributes()
        assert_tenant_run_id_forbidden_in_aggregate(entries)

    def test_planted_violation_is_schema_shape_valid_but_fails_consistency(self) -> None:
        schema = load_schema()
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)

        planted_bad_entry = {
            "name": "saena.tenant_id",
            "type": "string",
            "cardinality": "high",
            "pii": False,
            "contexts": {
                "tenant": "required",
                "system": "forbidden",
                # Rule violation: ADR-0006 rev.2 / ADR-0013 require this to
                # be "forbidden", never "required".
                "aggregate": "required",
            },
            "description": "Planted fixture for negative-path testing.",
        }

        # The planted entry is shape-valid against the schema in isolation
        # (schema cannot express the tenant_id/run_id-forbidden-in-aggregate
        # policy — that's a registry-lint-level rule, not a JSON Schema
        # constraint).
        shape_errors = list(validator.iter_errors([planted_bad_entry]))
        assert not shape_errors, (
            "expected the planted fixture to be schema-shape-valid so the "
            "test proves the consistency check (not the schema) catches "
            f"the violation; got shape errors: {shape_errors}"
        )

        # The registry-lint consistency check MUST catch it.
        with pytest.raises(AssertionError, match="V-AGG-TENANT"):
            assert_tenant_run_id_forbidden_in_aggregate([planted_bad_entry])

    def test_planted_violation_for_run_id_also_detected(self) -> None:
        planted_bad_entry = {
            "name": "saena.run_id",
            "type": "string",
            "cardinality": "high",
            "pii": False,
            "contexts": {
                "tenant": "required",
                "system": "forbidden",
                "aggregate": "optional",
            },
            "description": "Planted fixture for negative-path testing.",
        }
        with pytest.raises(AssertionError, match="V-AGG-TENANT"):
            assert_tenant_run_id_forbidden_in_aggregate([planted_bad_entry])
