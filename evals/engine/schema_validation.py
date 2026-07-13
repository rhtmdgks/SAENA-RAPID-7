"""Offline `jsonschema` validation against the frozen
`packages/contracts/json-schema/**` catalog — the `contract_compliance`
axis's primitive.

Same local-resolution approach `tests/contract/validate/_support.py`
documents (this module is an independent implementation under this unit's
own `evals/**` exclusive path, not a shared import of that module —
`tests/contract/**` is outside `evals/**`/`tests/unit/evals_harness/**`):
every `*.schema.json` file under `packages/contracts/json-schema/` is
pre-loaded into one `referencing.Registry`, keyed by its own declared
`$id`, so cross-file `$ref`s (e.g. `verification-result.schema.json`'s
`$ref` into `common/error-detail/v1`) resolve locally — `check-jsonschema`'s
CLI approach does not, because `$id` is an `https://schemas.the-saena.ai/...`
URI it tries to fetch over the network.

Pure/deterministic: no network I/O (the registry never dereferences an
`$id` over HTTP, only from the pre-loaded local documents), no wall-clock,
cached (`functools.lru_cache`) so repeated validation calls in the same
process do not re-walk/re-parse the schema tree.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[2]
CONTRACTS_JSON_SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "json-schema"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(CONTRACTS_JSON_SCHEMA_DIR.rglob("*.schema.json")):
        doc = _load_json(path)
        schema_id = doc.get("$id")
        if schema_id:
            resources.append((schema_id, Resource.from_contents(doc)))
    return Registry().with_resources(resources)


@cache
def _validator_for(schema_relpath: str) -> Draft202012Validator:
    schema_path = CONTRACTS_JSON_SCHEMA_DIR / schema_relpath
    if not schema_path.is_file():
        raise FileNotFoundError(
            f"contract schema not found: {schema_path} (relpath {schema_relpath!r} is relative "
            "to packages/contracts/json-schema/)"
        )
    schema = _load_json(schema_path)
    return Draft202012Validator(schema, registry=_registry())


def validate_payload(schema_relpath: str, payload: dict[str, Any]) -> list[str]:
    """Validate `payload` against the contract schema at `schema_relpath`
    (relative to `packages/contracts/json-schema/`).

    Returns a list of human-readable validation error messages — empty iff
    `payload` conforms. Never raises for a non-conformant payload (that is
    the expected, scoreable outcome); raises `FileNotFoundError` only if
    `schema_relpath` itself does not resolve to a real contract file (a
    fixture-authoring bug, not a scoreable case).
    """
    validator = _validator_for(schema_relpath)
    return [
        f"{'/'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    ]


def schema_exists(schema_relpath: str) -> bool:
    return (CONTRACTS_JSON_SCHEMA_DIR / schema_relpath).is_file()


__all__ = ["CONTRACTS_JSON_SCHEMA_DIR", "REPO_ROOT", "schema_exists", "validate_payload"]
