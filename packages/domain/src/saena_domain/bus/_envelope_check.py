"""Drain-time envelope validation, wired locally within `saena_domain.bus`.

Same discipline as `saena_domain.persistence._envelope_validation`'s own
module docstring (critic SHOULD-FIX 1 precedent, w2-07 review): this module
must not import `saena_domain.events._validation`/`saena_domain.events.
_topics` — private (underscore-prefixed) modules of a sibling patch unit —
nor edit `saena_domain.events` itself (outside this unit's exclusive-write
paths). It replicates the same two structural checks over the same public
libraries and the same read-only contract/catalog files
(`packages/contracts/**`, read-only per this unit's grant):

1. Dual (jsonschema 2020-12 + pydantic) structural validation — defense in
   depth. Every envelope reaching `OutboxPort.list_pending` should already be
   schema-valid (`OutboxPort.record`'s own contract, `saena_domain.
   persistence`), but `OutboxDrainer` re-checks at drain time rather than
   trusting that invariant blindly across a package boundary — a future
   adapter bug in `saena_domain.persistence` must never be able to publish a
   malformed envelope to a real topic.
2. Topic/producer 1:1 resolution (ADR-0013: `event_type` == AsyncAPI topic
   name, `producer` must be that channel's expected producer) — parsed from
   `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`, the same file
   `saena_domain.events._topics` parses, independently re-implemented here
   rather than imported (same "no private cross-module coupling" rule).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

# saena_domain/bus/_envelope_check.py -> saena_domain/bus -> saena_domain ->
# src -> packages/domain -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACTS_JSON_SCHEMA_DIR = _REPO_ROOT / "packages" / "contracts" / "json-schema"
_ASYNCAPI_PATH = (
    _REPO_ROOT / "packages" / "contracts" / "asyncapi" / "saena-events" / "v1" / "asyncapi.yaml"
)

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


def structural_errors(envelope: dict[str, Any]) -> list[str]:
    """Dual-validate `envelope` (jsonschema 2020-12 + pydantic); return every
    error message collected (empty list if valid)."""
    validator = _get_envelope_validator()
    messages = [error.message for error in validator.iter_errors(envelope)]
    try:
        SaenaEventEnvelopeV1.model_validate(envelope)
    except ValidationError as exc:
        messages.append(f"pydantic: {exc}")
    return messages


@dataclass(frozen=True)
class TopicInfo:
    """One AsyncAPI channel: its address (== `event_type`) and producer."""

    event_type: str
    expected_producer: str


class TopicCatalogError(RuntimeError):
    """The AsyncAPI file could not be parsed into a usable topic catalog."""


_PRODUCES_PATTERN = re.compile(r"^(?P<producer>\S+)\s+produces\s+(?P<event_type>\S+)\.$")

_catalog_lock = threading.Lock()
_catalog_cache: dict[str, TopicInfo] | None = None


def _parse_catalog(asyncapi_path: Path) -> dict[str, TopicInfo]:
    document = yaml.safe_load(asyncapi_path.read_text(encoding="utf-8"))
    channels = document.get("channels", {})
    operations = document.get("operations", {})

    catalog: dict[str, TopicInfo] = dict.fromkeys(channels, TopicInfo("", ""))
    for address in channels:
        catalog[address] = TopicInfo(event_type=address, expected_producer="")

    for op in operations.values():
        summary = op.get("summary", "")
        match = _PRODUCES_PATTERN.match(summary)
        if match is None:
            msg = (
                f"operation summary {summary!r} does not match the "
                "'<producer> produces <event_type>.' convention this catalog relies on"
            )
            raise TopicCatalogError(msg)
        event_type = match.group("event_type")
        producer = match.group("producer")
        if event_type not in catalog:
            msg = f"operation summary references unknown channel address {event_type!r}"
            raise TopicCatalogError(msg)
        catalog[event_type] = TopicInfo(event_type=event_type, expected_producer=producer)

    return catalog


def get_topic_catalog(asyncapi_path: Path = _ASYNCAPI_PATH) -> dict[str, TopicInfo]:
    """Return `{event_type: TopicInfo}`, parsed + process-cached once."""
    global _catalog_cache
    with _catalog_lock:
        if _catalog_cache is not None:
            return _catalog_cache
        _catalog_cache = _parse_catalog(asyncapi_path)
        return _catalog_cache


def topic_producer_errors(envelope: dict[str, Any]) -> list[str]:
    """ADR-0013 1:1 check: `event_type` must be a declared channel AND
    `producer` must match that channel's expected producer. Returns a list
    of human-readable messages (empty if both checks pass) — deliberately
    NOT an exception-raising function, so `OutboxDrainer` can combine these
    messages with `structural_errors`' output into one DLQ rejection reason.
    """
    event_type = envelope.get("event_type")
    producer = envelope.get("producer")
    catalog = get_topic_catalog()
    info = catalog.get(event_type) if isinstance(event_type, str) else None
    if info is None:
        return [f"event_type {event_type!r} does not match any declared AsyncAPI channel address"]
    if info.expected_producer != producer:
        return [
            f"producer {producer!r} is not the expected producer "
            f"{info.expected_producer!r} for event_type {event_type!r}"
        ]
    return []


__all__ = [
    "TopicCatalogError",
    "TopicInfo",
    "get_topic_catalog",
    "structural_errors",
    "topic_producer_errors",
]
