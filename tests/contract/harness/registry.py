"""packages/contracts/registry.json loading, schema validation, and
relational checks (ADR-0011 registry, registry.schema.json $comment).

registry.schema.json's own $comment states the relational constraints it
cannot express are "enforced by tests/contract/validate/test_registry.py
(W1 harness)". This module supplies the functions that check; the
`validate/` suite (w1-11) is expected to call them, and this harness's own
compat suite (`tests/contract/compat/test_n1_compat.py`) also consumes
`load_registry()`/`iter_entries()` directly to parametrize over contracts.

Nothing here hardcodes contract names -- all judgment is registry-data
driven (plan §2 "No contract names hardcoded").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

# tests/contract/harness/registry.py -> tests/contract/harness -> tests/contract
# -> tests -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"
REGISTRY_PATH = CONTRACTS_DIR / "registry.json"
REGISTRY_SCHEMA_PATH = CONTRACTS_DIR / "registry.schema.json"

# ADR-0011 $id scheme: https://schemas.the-saena.ai/{category}/{name}/v{major}/{name}.schema.json
_ID_PATTERN = re.compile(
    r"^https://schemas\.the-saena\.ai/"
    r"(?P<category>envelope|context|domain|event|common)/"
    r"(?P<name>[a-z0-9-]+)/"
    r"v(?P<major>[0-9]+)/"
    r"(?P<filename>[a-z0-9-]+)\.(?P<ext>schema\.json|yaml)$"
)


@dataclass(frozen=True)
class RegistryEntry:
    """Typed view over one `contracts[]` element of registry.json."""

    name: str
    catalog_name: str
    category: str
    compat_class: str
    signed: bool
    format: str
    major: int
    full_version: str
    id_: str
    owner: str
    status: str
    frozen_authority_adr: str | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> RegistryEntry:
        return RegistryEntry(
            name=data["name"],
            catalog_name=data["catalog_name"],
            category=data["category"],
            compat_class=data["compat_class"],
            signed=data["signed"],
            format=data["format"],
            major=data["major"],
            full_version=data["full_version"],
            id_=data["$id"],
            owner=data["owner"],
            status=data["status"],
            frozen_authority_adr=data.get("frozen_authority_adr"),
        )


def load_registry_raw(registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load registry.json as raw JSON (no validation)."""
    return json.loads(registry_path.read_text(encoding="utf-8"))


def load_registry_schema(schema_path: Path = REGISTRY_SCHEMA_PATH) -> dict[str, Any]:
    """Load registry.schema.json as raw JSON."""
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_registry_document(
    registry_path: Path = REGISTRY_PATH,
    schema_path: Path = REGISTRY_SCHEMA_PATH,
) -> None:
    """Validate registry.json against registry.schema.json.

    Raises jsonschema.exceptions.ValidationError on the first violation
    found (jsonschema.validate semantics). Callers that need every
    violation should use jsonschema.Draft202012Validator.iter_errors
    directly.
    """
    document = load_registry_raw(registry_path)
    schema = load_registry_schema(schema_path)
    jsonschema.validate(instance=document, schema=schema)


def load_registry(
    registry_path: Path = REGISTRY_PATH,
    schema_path: Path = REGISTRY_SCHEMA_PATH,
) -> list[RegistryEntry]:
    """Validate registry.json against its schema, then return typed entries."""
    validate_registry_document(registry_path, schema_path)
    document = load_registry_raw(registry_path)
    return [RegistryEntry.from_dict(raw) for raw in document.get("contracts", [])]


def iter_entries(registry_path: Path = REGISTRY_PATH) -> list[RegistryEntry]:
    """Convenience alias for load_registry() using default paths, for
    parametrization call sites (`tests/contract/compat/test_n1_compat.py`).
    """
    return load_registry(registry_path)


# --------------------------------------------------------------------------
# $id -> on-disk schema file path resolution (ADR-0011 1:1 rule)
# --------------------------------------------------------------------------


def schema_file_path_for_entry(entry: RegistryEntry, contracts_dir: Path = CONTRACTS_DIR) -> Path:
    """Resolve a registry entry's on-disk file path from its $id + format.

    ADR-0011 layout:
      format=json-schema -> packages/contracts/json-schema/<category>/<name>/
                             v<major>/<name>.schema.json
      format=openapi      -> packages/contracts/openapi/<name>/v<major>/openapi.yaml
      format=asyncapi      -> packages/contracts/asyncapi/<name>/v<major>/asyncapi.yaml
    """
    if entry.format == "json-schema":
        return (
            contracts_dir
            / "json-schema"
            / entry.category
            / entry.name
            / f"v{entry.major}"
            / f"{entry.name}.schema.json"
        )
    if entry.format == "openapi":
        return contracts_dir / "openapi" / entry.name / f"v{entry.major}" / "openapi.yaml"
    if entry.format == "asyncapi":
        return contracts_dir / "asyncapi" / entry.name / f"v{entry.major}" / "asyncapi.yaml"
    msg = f"unknown format {entry.format!r} for entry {entry.name!r}"
    raise ValueError(msg)


# --------------------------------------------------------------------------
# Relational checks (registry.schema.json $comment items 1-4)
# --------------------------------------------------------------------------


def check_name_major_unique(entries: list[RegistryEntry]) -> list[str]:
    """(1) name+major uniqueness across contracts[]."""
    seen: dict[tuple[str, int], int] = {}
    violations: list[str] = []
    for entry in entries:
        key = (entry.name, entry.major)
        seen[key] = seen.get(key, 0) + 1
    for (name, major), count in seen.items():
        if count > 1:
            violations.append(f"duplicate name+major: {name} v{major} appears {count} times")
    return violations


def check_full_version_major_prefix(entries: list[RegistryEntry]) -> list[str]:
    """(2) full_version's major-version prefix (X in X.Y.Z) equals major."""
    violations: list[str] = []
    for entry in entries:
        prefix = entry.full_version.split(".", 1)[0]
        if prefix != str(entry.major):
            violations.append(
                f"{entry.name}: full_version {entry.full_version!r} major prefix "
                f"{prefix!r} != major field {entry.major}"
            )
    return violations


def check_id_category_and_path(entries: list[RegistryEntry]) -> list[str]:
    """(3)+(4) $id path 1:1-maps to the on-disk file; category matches the
    $id path's category segment.
    """
    violations: list[str] = []
    for entry in entries:
        match = _ID_PATTERN.match(entry.id_)
        if match is None:
            violations.append(
                f"{entry.name}: $id {entry.id_!r} does not match ADR-0011 $id pattern"
            )
            continue
        if match.group("category") != entry.category:
            violations.append(
                f"{entry.name}: $id category segment {match.group('category')!r} "
                f"!= entry category {entry.category!r}"
            )
        if int(match.group("major")) != entry.major:
            violations.append(
                f"{entry.name}: $id major segment v{match.group('major')} "
                f"!= entry major {entry.major}"
            )
    return violations


def check_schema_file_exists(
    entries: list[RegistryEntry], contracts_dir: Path = CONTRACTS_DIR
) -> list[str]:
    """Schema file referenced by each entry's $id/format must exist on disk."""
    violations: list[str] = []
    for entry in entries:
        path = schema_file_path_for_entry(entry, contracts_dir)
        if not path.is_file():
            violations.append(f"{entry.name}: expected schema file missing at {path}")
    return violations


def all_relational_violations(
    entries: list[RegistryEntry], contracts_dir: Path = CONTRACTS_DIR
) -> list[str]:
    """Run every relational check and return the combined violation list."""
    violations: list[str] = []
    violations += check_name_major_unique(entries)
    violations += check_full_version_major_prefix(entries)
    violations += check_id_category_and_path(entries)
    violations += check_schema_file_exists(entries, contracts_dir)
    return violations
