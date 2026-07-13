"""Shared jsonschema validation helper for tests/unit/domain_execution.

Not itself a test module (no `test_` prefix). Mirrors
`tests/contract/validate/_support.py` / `saena_domain.events._validation`'s
proven local `$ref` resolution approach: a `jsonschema.Draft202012Validator`
backed by a `referencing.Registry` pre-loaded with every sibling document
this test suite's payload schemas `$ref` (their `$id` is an
`https://schemas.the-saena.ai/...` URI a naive resolver would try to fetch
over the network) so resolution stays fully local, with no dependency on
`saena_domain.events` internals (this package's own read-only contract
consumption, kept independent of that other patch unit's module).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# tests/unit/domain_execution/_schema_support.py -> domain_execution -> unit
# -> tests -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_JSON_SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "json-schema"

ERROR_DETAIL_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "error-detail" / "v1" / "error-detail.schema.json"
)
IDENTIFIERS_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
)

_SUPPORT_DOC_PATHS = (ERROR_DETAIL_SCHEMA_PATH, IDENTIFIERS_SCHEMA_PATH)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_validator(schema_path: Path) -> Draft202012Validator:
    """Build a `Draft202012Validator` for `schema_path`, with a local
    registry pre-loaded so any `$ref` to `common/error-detail/v1` or
    `common/identifiers/v1` resolves without a network fetch."""
    schema = load_json(schema_path)
    resources: list[tuple[str, Resource]] = [(schema["$id"], Resource.from_contents(schema))]
    for support_path in _SUPPORT_DOC_PATHS:
        doc = load_json(support_path)
        resources.append((doc["$id"], Resource.from_contents(doc)))
    registry: Registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def schema_errors(schema_path: Path, instance: dict[str, Any]) -> list[str]:
    validator = build_validator(schema_path)
    return [error.message for error in validator.iter_errors(instance)]


REPO_INTAKEN_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR / "event" / "repo-intaken" / "v1" / "repo-intaken.schema.json"
)
PATCH_UNIT_COMPLETED_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR
    / "event"
    / "patch-unit-completed"
    / "v1"
    / "patch-unit-completed.schema.json"
)
QUALITY_GATE_RESULT_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR
    / "event"
    / "quality-gate-result"
    / "v1"
    / "quality-gate-result.schema.json"
)
SITE_INVENTORY_COMPLETED_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR
    / "event"
    / "site-inventory-completed"
    / "v1"
    / "site-inventory-completed.schema.json"
)

__all__ = [
    "ERROR_DETAIL_SCHEMA_PATH",
    "IDENTIFIERS_SCHEMA_PATH",
    "PATCH_UNIT_COMPLETED_SCHEMA_PATH",
    "QUALITY_GATE_RESULT_SCHEMA_PATH",
    "REPO_INTAKEN_SCHEMA_PATH",
    "SITE_INVENTORY_COMPLETED_SCHEMA_PATH",
    "build_validator",
    "load_json",
    "schema_errors",
]
