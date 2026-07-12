"""Dual validation: jsonschema (2020-12, local `referencing.Registry`) + pydantic.

Mirrors the pattern established by `tests/contract/validate/_support.py`
(`build_validator`) and its docstring's citation of
`tests/contract/test_envelope_fixtures.py`: `check-jsonschema`'s CLI
subprocess approach does not resolve this catalog's cross-file `$ref`s out of
the box because each schema's `$id` is an `https://schemas.the-saena.ai/...`
URI it tries to fetch over the network. The fix — used here exactly as in
the contract test suite — is a `jsonschema.Draft202012Validator` backed by a
`referencing.Registry` pre-loaded with every sibling document keyed by its
own declared `$id`, so `$ref` resolution stays fully local.

This module reads (never writes) three files under `packages/contracts/`
(read-only per this patch unit's path grant):
  - envelope/event-envelope/v1/event-envelope.schema.json
  - common/identifiers/v1/identifiers.schema.json
  - common/engine-id/v1/engine-id.schema.json
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# saena_domain/events/_validation.py -> saena_domain/events -> saena_domain
# -> src -> packages/domain -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACTS_JSON_SCHEMA_DIR = _REPO_ROOT / "packages" / "contracts" / "json-schema"

ENVELOPE_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "envelope" / "event-envelope" / "v1" / "event-envelope.schema.json"
)
IDENTIFIERS_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
)
ENGINE_ID_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "common" / "engine-id" / "v1" / "engine-id.schema.json"
)

_lock = threading.Lock()
_validator_cache: Draft202012Validator | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_envelope_validator() -> Draft202012Validator:
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    resources: list[tuple[str, Resource]] = [(schema["$id"], Resource.from_contents(schema))]
    for extra_path in (IDENTIFIERS_SCHEMA_PATH, ENGINE_ID_SCHEMA_PATH):
        extra_doc = _load_json(extra_path)
        resources.append((extra_doc["$id"], Resource.from_contents(extra_doc)))
    registry: Registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def get_envelope_validator() -> Draft202012Validator:
    """Return the process-cached envelope `Draft202012Validator`."""
    global _validator_cache
    with _lock:
        if _validator_cache is None:
            _validator_cache = _build_envelope_validator()
        return _validator_cache


def jsonschema_errors(instance: dict[str, Any]) -> list[str]:
    """Validate `instance` against the envelope contract; return error messages."""
    validator = get_envelope_validator()
    return [error.message for error in validator.iter_errors(instance)]
