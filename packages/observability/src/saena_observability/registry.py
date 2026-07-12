"""Read-only loader for the W0 telemetry attribute registry (ADR-0016).

Consumes `packages/observability/registry/attributes.json` and
`redaction-rules.yaml` — those files are W0 SSOT (single-owner boundary,
ADR-0016 constraints) and are never written by this module. This module
only parses and exposes them as typed lookup structures for
`saena_observability.redaction`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

# packages/observability/src/saena_observability/registry.py -> packages/observability
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_DIR = _PACKAGE_ROOT / "registry"
ATTRIBUTES_JSON_PATH = _REGISTRY_DIR / "attributes.json"
REDACTION_RULES_PATH = _REGISTRY_DIR / "redaction-rules.yaml"

ContextRule = str  # "required" | "optional" | "forbidden"


@dataclass(frozen=True, slots=True)
class AttributeEntry:
    """One `attributes.json` registry entry (ADR-0016 registry schema).

    `contexts` is a `MappingProxyType` (read-only view), not a plain
    `dict` — `load_attribute_registry()` is `lru_cache`d, so every caller
    receives the *same* `AttributeEntry` instances; a plain mutable dict
    would let one caller's in-place edit corrupt the shared cached copy
    for every other caller in the process.
    """

    name: str
    type: str
    cardinality: str
    pii: bool
    contexts: MappingProxyType[str, ContextRule]
    description: str


@dataclass(frozen=True, slots=True)
class DenylistPattern:
    """One `redaction-rules.yaml` `denylist_patterns` entry."""

    id: str
    pattern: re.Pattern[str]
    applies_to: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class ViolationRule:
    """One `redaction-rules.yaml` `violation_rules` entry (e.g. V-AGG-TENANT)."""

    id: str
    context: str
    forbidden_attributes: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class RedactionRules:
    export_policy: str
    denylist_patterns: tuple[DenylistPattern, ...]
    violation_rules: tuple[ViolationRule, ...]


@lru_cache(maxsize=1)
def load_attribute_registry() -> dict[str, AttributeEntry]:
    """Load `attributes.json` into a name -> `AttributeEntry` mapping.

    Cached (registry files are read-only inputs for this package's runtime;
    they change only via the W0-owned patch unit that ships them).
    """
    with ATTRIBUTES_JSON_PATH.open(encoding="utf-8") as fh:
        raw: list[dict[str, Any]] = json.load(fh)
    return {
        entry["name"]: AttributeEntry(
            name=entry["name"],
            type=entry["type"],
            cardinality=entry["cardinality"],
            pii=entry["pii"],
            contexts=MappingProxyType(dict(entry["contexts"])),
            description=entry["description"],
        )
        for entry in raw
    }


@lru_cache(maxsize=1)
def load_redaction_rules() -> RedactionRules:
    """Load `redaction-rules.yaml` into a typed `RedactionRules` structure."""
    with REDACTION_RULES_PATH.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    denylist = tuple(
        DenylistPattern(
            id=item["id"],
            pattern=re.compile(item["pattern"]),
            applies_to=tuple(item["applies_to"]),
            description=item["description"],
        )
        for item in raw.get("denylist_patterns", [])
    )
    violations = tuple(
        ViolationRule(
            id=item["id"],
            context=item["context"],
            forbidden_attributes=tuple(item["forbidden_attributes"]),
            description=item["description"],
        )
        for item in raw.get("violation_rules", [])
    )
    return RedactionRules(
        export_policy=raw["export_policy"],
        denylist_patterns=denylist,
        violation_rules=violations,
    )


def is_allowlisted(attribute_name: str) -> bool:
    """Return True iff `attribute_name` is a registered `saena.*` attribute.

    Non-`saena.*` names (e.g. OTel semantic-convention baseline keys) are
    outside this registry's allowlist scope entirely; callers that need to
    pass through non-`saena.*` keys make that decision explicitly — this
    function only answers "is this a registered saena.* attribute".
    """
    return attribute_name in load_attribute_registry()
