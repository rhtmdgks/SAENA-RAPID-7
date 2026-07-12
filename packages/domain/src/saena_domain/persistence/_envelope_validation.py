"""Envelope dual validation, wired locally within `saena_domain.persistence`.

Critic SHOULD-FIX 1 (w2-07 review): `OutboxPort`'s `record()` must validate a
caller-given envelope is structurally valid before storing it, but this
module must not import `saena_domain.events._validation` — a private
(underscore-prefixed) module of a sibling patch unit — nor edit
`saena_domain.events` itself (outside this unit's exclusive-write paths).
This module replicates the SAME two public calls
`saena_domain.events._validation.jsonschema_errors` makes
(`jsonschema.Draft202012Validator` via the public `jsonschema` API, backed by
a `referencing.Registry`, plus `SaenaEventEnvelopeV1.model_validate` — both
already public APIs) against the same read-only contract JSON Schema files
under `packages/contracts/json-schema/` (read-only per this unit's grant,
same files `saena_domain.events` itself reads). No `saena_domain.events`
import, private or public, appears in this module — the two implementations
are independent, deliberately duplicated wiring over the same public
libraries and the same read-only SSOT files, not a shared private helper.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

# saena_domain/persistence/_envelope_validation.py -> saena_domain/persistence
# -> saena_domain -> src -> packages/domain -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACTS_JSON_SCHEMA_DIR = _REPO_ROOT / "packages" / "contracts" / "json-schema"

_ENVELOPE_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "envelope" / "event-envelope" / "v1" / "event-envelope.schema.json"
)
_IDENTIFIERS_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
)
_ENGINE_ID_SCHEMA_PATH = (
    _CONTRACTS_JSON_SCHEMA_DIR / "common" / "engine-id" / "v1" / "engine-id.schema.json"
)

_lock = threading.Lock()
_validator_cache: Draft202012Validator | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_envelope_validator() -> Draft202012Validator:
    schema = _load_json(_ENVELOPE_SCHEMA_PATH)
    resources: list[tuple[str, Resource]] = [(schema["$id"], Resource.from_contents(schema))]
    for extra_path in (_IDENTIFIERS_SCHEMA_PATH, _ENGINE_ID_SCHEMA_PATH):
        extra_doc = _load_json(extra_path)
        resources.append((extra_doc["$id"], Resource.from_contents(extra_doc)))
    registry: Registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def _get_envelope_validator() -> Draft202012Validator:
    global _validator_cache
    with _lock:
        if _validator_cache is None:
            _validator_cache = _build_envelope_validator()
        return _validator_cache


def validate_envelope(envelope: dict[str, Any]) -> list[str]:
    """Dual-validate `envelope` (jsonschema 2020-12 + pydantic); return every
    error message collected (empty list if valid)."""
    validator = _get_envelope_validator()
    messages = [error.message for error in validator.iter_errors(envelope)]
    try:
        SaenaEventEnvelopeV1.model_validate(envelope)
    except ValidationError as exc:
        messages.append(f"pydantic: {exc}")
    return messages


__all__ = ["validate_envelope"]
