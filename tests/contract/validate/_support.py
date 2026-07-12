"""Shared helpers for per-contract validate/ modules (w1-11).

Not itself a test module (no test_ prefix) -- imported by the
per-contract modules in this directory. Centralizes the
jsonschema.Draft202012Validator + referencing.Registry construction
pattern established by `tests/contract/test_envelope_fixtures.py`
(module docstring: check-jsonschema's CLI subprocess approach does not
resolve this catalog's cross-file $refs out of the box because $id is
an https://schemas.the-saena.ai/... URI it tries to fetch over the
network -- jsonschema+referencing.Registry pre-loaded with sibling
documents is the proven local-resolution approach, reused here rather
than re-invented per contract module).

Also re-exports `harness.util.strip_metadata` under the name this
directory's modules use, and adds `load_json`/`iter_fixtures` glue.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.util import strip_metadata
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

VALIDATE_DIR = Path(__file__).resolve().parent
CONTRACT_TESTS_DIR = VALIDATE_DIR.parent
REPO_ROOT = CONTRACT_TESTS_DIR.parent.parent
CONTRACTS_JSON_SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "json-schema"
FIXTURES_DIR = CONTRACT_TESTS_DIR / "fixtures"

__all__ = [
    "CONTRACTS_JSON_SCHEMA_DIR",
    "FIXTURES_DIR",
    "REPO_ROOT",
    "build_validator",
    "fixture_pairs",
    "load_json",
    "strip_metadata",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_validator(
    schema_path: Path, extra_resource_paths: list[Path] | None = None
) -> Draft202012Validator:
    """Build a Draft202012Validator for `schema_path`, pre-loading a
    referencing.Registry with `schema_path` itself plus every path in
    `extra_resource_paths` (the schema's cross-file $ref targets),
    keyed by each document's own declared $id -- mirrors
    test_envelope_fixtures.py::_build_validator.
    """
    schema = load_json(schema_path)
    resources: list[tuple[str, Resource]] = [(schema["$id"], Resource.from_contents(schema))]
    for extra_path in extra_resource_paths or []:
        extra_doc = load_json(extra_path)
        resources.append((extra_doc["$id"], Resource.from_contents(extra_doc)))
    registry: Registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def fixture_pairs(fixture_dir: Path) -> list[Path]:
    """Sorted list of *.json fixture paths directly under `fixture_dir`."""
    if not fixture_dir.is_dir():
        return []
    return sorted(fixture_dir.glob("*.json"))


# Common cross-file $ref targets, named for readability at call sites.
IDENTIFIERS_SCHEMA = (
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
)
ENGINE_ID_SCHEMA = (
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "engine-id" / "v1" / "engine-id.schema.json"
)
ERROR_DETAIL_SCHEMA = (
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "error-detail" / "v1" / "error-detail.schema.json"
)
