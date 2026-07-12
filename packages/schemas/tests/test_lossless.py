"""CODEGEN_LOSSLESS gate tests (Lead verdict, 2026-07-12 — BINDING mechanism A).

For every OPEN-class generated root model: build a schema-valid instance,
inject nested + top-level unknown fields, round-trip it through
`model_validate` -> `model_dump(mode="json", by_alias=True, exclude_none=True)`,
and assert the original data is a recursive subset of the dump (lossless —
unknown fields survive the round-trip because the root carries
`extra='allow'`).

For every CLOSED-class generated root model: build a schema-valid instance,
add an unrecognized top-level field, and assert `model_validate` raises
`pydantic.ValidationError` (sealed — `extra='forbid'`).

Plus an envelope parity smoke test: the 3 valid envelope fixtures parse
through the generated union root model, and the `engine-id-google.json`
invalid fixture is rejected somewhere in the validation chain (the closed
`payload.engine_id` enum).

Instance construction is schema-driven (walks each original JSON Schema's
own `required`/`properties`/`pattern`/`enum`/`$ref`/`anyOf`/`oneOf`), not
hardcoded per-contract fixtures — this keeps the test resilient to field
additions in packages/contracts without needing a parallel hand-maintained
fixture per contract. Every generated instance's ground truth is verified
independently by check-jsonschema-equivalent, in-process
`jsonschema.Draft202012Validator` validation before it is ever handed to a
pydantic model (`test_generated_instances_are_schema_valid`), so a bug in
the instance builder cannot silently mask a codegen regression.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts" / "json-schema"
SCHEMAS_PKG_DIR = REPO_ROOT / "packages" / "schemas" / "saena_schemas"
ENVELOPE_FIXTURES_DIR = REPO_ROOT / "tests" / "contract" / "fixtures" / "envelope"

# OPEN-class contract set — MUST stay in lockstep with the `codegen` justfile
# recipe's OPEN_CONTRACTS list (same $comment applies: hardcoded until
# packages/contracts/registry.json carries compat_class per contract, w1-15).
OPEN_CONTRACTS: dict[str, str] = {
    "context/workspace_context_v1": "context/workspace-context/v1",
    "context/project_context_v1": "context/project-context/v1",
    "context/site_context_v1": "context/site-context/v1",
    "context/run_context_lifecycle_v1": "context/run-context-lifecycle/v1",
    "domain/verification_result_v1": "domain/verification-result/v1",
}

CLOSED_CONTRACTS: dict[str, str] = {
    "common/error_detail_v1": "common/error-detail/v1",
    "common/problem_detail_v1": "common/problem-detail/v1",
    "context/actor_context_v1": "context/actor-context/v1",
    "context/run_context_experiment_v1": "context/run-context-experiment/v1",
    "context/tenant_context_v1": "context/tenant-context/v1",
    "domain/approval_decision_v1": "domain/approval-decision/v1",
    "domain/audit_event_v1": "domain/audit-event/v1",
    "domain/change_plan_v1": "domain/change-plan/v1",
    "domain/patch_artifact_v1": "domain/patch-artifact/v1",
    "domain/source_snapshot_v1": "domain/source-snapshot/v1",
}


# ---------------------------------------------------------------------------
# Schema-driven minimal-instance builder (no network, no hardcoded fixtures).
# ---------------------------------------------------------------------------


def _resolve_ref(ref: str, base_dir: Path) -> tuple[dict[str, Any], Path]:
    file_part, _, fragment = ref.partition("#")
    target_path = (base_dir / file_part).resolve() if file_part else None
    doc: Any = json.loads(target_path.read_text(encoding="utf-8")) if target_path else None
    node = doc
    if fragment:
        for part in fragment.strip("/").split("/"):
            if part:
                node = node[part]
    return node, (target_path.parent if target_path else base_dir)


# Exhaustive lookup of the `pattern` values actually used across
# packages/contracts (verified, not a general regex-to-string generator —
# safer for a small fixed contract set: see test_generated_instances_are_schema_valid).
_PATTERN_EXAMPLES: dict[str, str] = {
    r"^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$": "acme-co",
    r"^saena-tenant-[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$": "saena-tenant-acme-co",
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$": "1.0.0",
    r"^[0-9]+\.[0-9]+\.[0-9]+$": "1.0.0",
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$": "2026-07-12T00:00:00Z",
    r"^sha256:[0-9a-f]{64}$": "sha256:" + "a" * 64,
    r"^[0-9a-f]{40}$": "a" * 40,
    r"^[a-z0-9+.-]+://[^?#]+$": "https://example.com/x",
    r"^[0-9a-f]{7,40}$": "a" * 40,
    r"^saena\.[a-z_]+\.[a-z_]+$": "saena.validation.bad_input",
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$": (
        "018f3a1e-7c2b-7c3e-9b1a-4e2f1a9d3c7b"
    ),
    r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}\.v[0-9]+$": "patch.unit.completed.v1",
    r"^[0-9a-f]{32}$": "a" * 32,
    r"^[^?#]+$": "opaque-cell-ref-1",
    r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$": "example.com",
}

_COUNTER = {"n": 0}


def _next_placeholder() -> str:
    _COUNTER["n"] += 1
    return f"example-string-{_COUNTER['n']}"


def build_example(schema: dict[str, Any], base_dir: Path) -> Any:
    """Build a minimal, schema-conforming instance from a JSON Schema node."""
    if "$ref" in schema:
        node, new_base = _resolve_ref(schema["$ref"], base_dir)
        return build_example(node, new_base)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            branches = schema[combinator]
            non_null = [b for b in branches if b.get("type") != "null"]
            return build_example((non_null or branches)[0], base_dir)

    stype = schema.get("type")

    if (
        stype == "object"
        and "properties" not in schema
        and isinstance(schema.get("additionalProperties"), dict)
    ):
        # Open key-set object (e.g. ChangePlan.hypotheses[].expected_effect_distribution):
        # synthesize enough keys to satisfy minProperties.
        min_props = schema.get("minProperties", 0)
        value_schema = schema["additionalProperties"]
        return {f"key-{i}": build_example(value_schema, base_dir) for i in range(max(min_props, 1))}

    if stype == "object" or ("properties" in schema and stype is None):
        out: dict[str, Any] = {}
        props = schema.get("properties", {})
        required = list(schema.get("required", list(props.keys())))
        # Minimal allOf/if/then support: this contract set only uses
        # discriminator-conditional-requires (ActorContext.actor_type,
        # AuditEvent.scope). Prefer the enum branch that does NOT trigger
        # the conditional, where one exists, so the minimal instance stays
        # schema-valid without implementing general if/then evaluation.
        for discriminator_key in ("actor_type", "scope"):
            if discriminator_key in props and "enum" in props[discriminator_key]:
                props = dict(props)
                props[discriminator_key] = dict(props[discriminator_key])
                if "system" in props[discriminator_key]["enum"]:
                    props[discriminator_key]["enum"] = ["system"]
        for key in required:
            out[key] = build_example(props[key], base_dir)
        return out

    if stype == "array":
        items = schema.get("items", {"type": "string"})
        min_items = schema.get("minItems", 1) or 1
        return [build_example(items, base_dir) for _ in range(min_items)]
    if stype == "integer":
        return max(schema.get("minimum", 1), 1)
    if stype == "number":
        return 1.0
    if stype == "boolean":
        return True
    if stype == "string":
        if "pattern" in schema:
            example = _PATTERN_EXAMPLES.get(schema["pattern"])
            if example is None:
                raise ValueError(f"no known example for pattern {schema['pattern']!r}")
            return example
        if schema.get("format") == "uuid":
            return "018f3a1e-7c2b-7c3e-9b1a-4e2f1a9d3c7b"
        return _next_placeholder()
    raise ValueError(f"cannot build example for schema node {schema!r}")


def _load_schema(rel_dir: str) -> tuple[dict[str, Any], Path]:
    schema_dir = CONTRACTS_DIR / rel_dir
    (schema_path,) = schema_dir.glob("*.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8")), schema_path.parent


def _build_registry() -> Registry:
    resources = []
    for path in CONTRACTS_DIR.rglob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


_REGISTRY = _build_registry()


def _assert_schema_valid(schema: dict[str, Any], instance: Any) -> None:
    validator = Draft202012Validator(schema, registry=_REGISTRY)
    errors = list(validator.iter_errors(instance))
    assert not errors, "generated instance is not schema-valid:\n" + "\n".join(
        f"  {'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors
    )


# ---------------------------------------------------------------------------
# Root model resolution — mirrors tools/validation/codegen-patch-openroot.py's
# "root model = the generated class whose field names match the schema's own
# top-level properties" rule (see that script's docstring for why this beats
# class-definition-order or title-string-transform heuristics).
# ---------------------------------------------------------------------------


def _import_root_model(module_dir_name_by_category: str) -> type[BaseModel]:
    category, module_name = module_dir_name_by_category.split("/", 1)
    module = importlib.import_module(f"saena_schemas.{category}.{module_name}")
    schema, _ = _load_schema((OPEN_CONTRACTS | CLOSED_CONTRACTS)[module_dir_name_by_category])
    expected_fields = frozenset(schema["properties"].keys())
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and frozenset(obj.model_fields.keys()) == expected_fields
        ):
            return obj
    raise AssertionError(
        f"no generated class in saena_schemas.{category}.{module_name} matches "
        f"schema root fields {sorted(expected_fields)}"
    )


def _recursive_subset(expected: Any, actual: Any) -> bool:
    """True if every key/value in `expected` is present (recursively) in `actual`.

    Used to prove losslessness: the dumped output must contain everything the
    original input had, including fields the schema doesn't know about
    (unknown/extra fields on an OPEN-class root).
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _recursive_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(_recursive_subset(e, a) for e, a in zip(expected, actual, strict=True))
    return expected == actual


# ---------------------------------------------------------------------------
# Sanity: every builder-generated instance is independently schema-valid
# (ground truth via in-process jsonschema.Draft202012Validator — the same
# mechanism tests/contract/test_envelope_fixtures.py uses, since the
# check-jsonschema CLI cannot resolve this repo's non-resolvable
# schemas.the-saena.ai $id scheme without network access).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract_dir", sorted(OPEN_CONTRACTS) + sorted(CLOSED_CONTRACTS), ids=str)
def test_generated_instances_are_schema_valid(contract_dir: str) -> None:
    schema_rel = (OPEN_CONTRACTS | CLOSED_CONTRACTS)[contract_dir]
    schema, base_dir = _load_schema(schema_rel)
    instance = build_example(schema, base_dir)
    _assert_schema_valid(schema, instance)


# ---------------------------------------------------------------------------
# OPEN-class: unknown fields (top-level + nested) survive the round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract_dir", sorted(OPEN_CONTRACTS), ids=str)
def test_open_root_is_lossless_for_unknown_fields(contract_dir: str) -> None:
    schema, base_dir = _load_schema(OPEN_CONTRACTS[contract_dir])
    instance = build_example(schema, base_dir)
    _assert_schema_valid(schema, instance)

    with_unknown = dict(instance)
    with_unknown["__unknown_top_level_field"] = {"nested": {"deeply": ["unknown", "values", 1]}}
    with_unknown["__another_unknown"] = "plain-string-value"

    model_cls = _import_root_model(contract_dir)
    model_config = getattr(model_cls, "model_config", {})
    assert model_config.get("extra") == "allow", (
        f"{contract_dir}: expected root model_config extra='allow' (OPEN-class), "
        f"found {model_config.get('extra')!r}"
    )

    parsed = model_cls.model_validate(with_unknown)
    dumped = parsed.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert _recursive_subset(with_unknown, dumped), (
        f"{contract_dir}: round-trip lost data — input was not a subset of the dump.\n"
        f"input={with_unknown!r}\ndump={dumped!r}"
    )


# ---------------------------------------------------------------------------
# CLOSED-class: an extra top-level field is rejected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract_dir", sorted(CLOSED_CONTRACTS), ids=str)
def test_closed_root_rejects_extra_top_level_field(contract_dir: str) -> None:
    schema, base_dir = _load_schema(CLOSED_CONTRACTS[contract_dir])
    instance = build_example(schema, base_dir)
    _assert_schema_valid(schema, instance)

    with_extra = dict(instance)
    with_extra["__unexpected_extra_field"] = "should-be-rejected"

    model_cls = _import_root_model(contract_dir)
    model_config = getattr(model_cls, "model_config", {})
    assert model_config.get("extra") == "forbid", (
        f"{contract_dir}: expected root model_config extra='forbid' (CLOSED-class), "
        f"found {model_config.get('extra')!r}"
    )

    with pytest.raises(ValidationError):
        model_cls.model_validate(with_extra)


# ---------------------------------------------------------------------------
# Envelope parity smoke: valid fixtures parse; engine-id-google is rejected
# somewhere in the validation chain (closed payload.engine_id enum).
# ---------------------------------------------------------------------------


def _load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.mark.parametrize(
    "fixture_name",
    [
        "tenant-patch-unit-completed-v1.json",
        "system-adapter-config-updated-v1.json",
        "aggregate-strategy-card-eligible-v1.json",
    ],
)
def test_envelope_valid_fixtures_parse(fixture_name: str) -> None:
    from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

    data = _load_fixture(ENVELOPE_FIXTURES_DIR / "valid" / fixture_name)
    parsed = SaenaEventEnvelopeV1.model_validate(data)
    assert parsed.root is not None


def test_envelope_engine_id_google_fixture_rejected() -> None:
    from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

    data = _load_fixture(ENVELOPE_FIXTURES_DIR / "invalid" / "engine-id-google.json")
    with pytest.raises(ValidationError):
        SaenaEventEnvelopeV1.model_validate(data)


# ---------------------------------------------------------------------------
# Inventory sanity: the OPEN/CLOSED lists above must stay exhaustive over
# every contract directory actually generated (minus envelope/common
# $defs-only or bare-enum files, which have no object root to classify).
# ---------------------------------------------------------------------------


def test_open_and_closed_lists_cover_all_generated_object_root_contracts() -> None:
    covered = set(OPEN_CONTRACTS) | set(CLOSED_CONTRACTS)
    all_module_dirs = {
        f"{p.parent.parent.name}/{p.parent.name}" for p in SCHEMAS_PKG_DIR.glob("*/*/__init__.py")
    }
    # common/identifiers_v1 ($defs-only) and common/engine_id_v1 (bare string
    # enum root) have no object root — excluded by design (see
    # tools/validation/codegen-patch-openroot.py docstring). envelope/* is the
    # FROZEN class (ADR-0012), covered by the dedicated parity smoke tests
    # above rather than the generic open/closed loop.
    excluded = {"common/identifiers_v1", "common/engine_id_v1", "envelope/event_envelope_v1"}
    uncovered = all_module_dirs - covered - excluded
    assert not uncovered, f"contract module(s) not classified open/closed: {uncovered}"
