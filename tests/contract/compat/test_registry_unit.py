"""Unit tests for harness.registry -- schema loading/validation, entry
parsing, $id -> file path resolution, and relational checks. Uses
synthetic tempdir registry.json/registry.schema.json fixtures alongside
the real packages/contracts/registry.json (currently empty, W1
bootstrap) so both the real and synthetic paths are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from harness import registry as registry_mod
from harness.registry import RegistryEntry


def test_real_registry_loads_and_validates() -> None:
    """The actual packages/contracts/registry.json (populated at w1-15)
    must load and validate cleanly against the actual registry.schema.json.
    """
    entries = registry_mod.load_registry()
    assert len(entries) == 43, (
        "w1-15 populated 26 entries (24 json-schema + openapi + asyncapi); "
        "w4-10 landed 12 more (7 event + 5 domain json-schema contracts); "
        "w5-02 landed 5 more (3 event payloads + 2 domain measurement records)"
    )
    names = [e.name for e in entries]
    assert len(set((e.name, e.major) for e in entries)) == 43, "name+major unique"
    assert "event-envelope" in names and "change-plan" in names


def test_real_registry_relational_checks_are_clean_when_empty() -> None:
    entries = registry_mod.load_registry()
    assert registry_mod.all_relational_violations(entries) == []


def _sample_entry_dict(
    name: str = "sample-contract",
    major: int = 1,
    category: str = "domain",
    compat_class: str = "closed",
) -> dict:
    return {
        "name": name,
        "catalog_name": "SampleContract",
        "category": category,
        "compat_class": compat_class,
        "signed": False,
        "format": "json-schema",
        "major": major,
        "full_version": f"{major}.0.0",
        "$id": f"https://schemas.the-saena.ai/{category}/{name}/v{major}/{name}.schema.json",
        "owner": "contracts-steward",
        "status": "active",
    }


def test_registry_entry_from_dict_round_trips() -> None:
    data = _sample_entry_dict()
    entry = RegistryEntry.from_dict(data)
    assert entry.name == "sample-contract"
    assert entry.catalog_name == "SampleContract"
    assert entry.compat_class == "closed"
    assert entry.signed is False
    assert entry.major == 1
    assert entry.frozen_authority_adr is None


def test_registry_entry_from_dict_with_frozen_authority_adr() -> None:
    data = _sample_entry_dict(compat_class="frozen")
    data["frozen_authority_adr"] = "ADR-0013"
    entry = RegistryEntry.from_dict(data)
    assert entry.frozen_authority_adr == "ADR-0013"


def test_schema_file_path_for_entry_json_schema() -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict())
    path = registry_mod.schema_file_path_for_entry(entry, contracts_dir=Path("/root/contracts"))
    assert path == Path(
        "/root/contracts/json-schema/domain/sample-contract/v1/sample-contract.schema.json"
    )


def test_schema_file_path_for_entry_openapi() -> None:
    data = _sample_entry_dict(name="contract-validation")
    data["format"] = "openapi"
    entry = RegistryEntry.from_dict(data)
    path = registry_mod.schema_file_path_for_entry(entry, contracts_dir=Path("/root/contracts"))
    assert path == Path("/root/contracts/openapi/contract-validation/v1/openapi.yaml")


def test_schema_file_path_for_entry_asyncapi() -> None:
    data = _sample_entry_dict(name="saena-events")
    data["format"] = "asyncapi"
    entry = RegistryEntry.from_dict(data)
    path = registry_mod.schema_file_path_for_entry(entry, contracts_dir=Path("/root/contracts"))
    assert path == Path("/root/contracts/asyncapi/saena-events/v1/asyncapi.yaml")


def test_schema_file_path_for_entry_unknown_format_raises() -> None:
    data = _sample_entry_dict()
    data["format"] = "json-schema"
    entry = RegistryEntry.from_dict(data)
    object.__setattr__(entry, "format", "bogus-format")
    with pytest.raises(ValueError, match="unknown format"):
        registry_mod.schema_file_path_for_entry(entry)


# --------------------------------------------------------------------------
# Relational checks (synthetic entries)
# --------------------------------------------------------------------------


def test_check_name_major_unique_detects_duplicate() -> None:
    e1 = RegistryEntry.from_dict(_sample_entry_dict(name="dup", major=1))
    e2 = RegistryEntry.from_dict(_sample_entry_dict(name="dup", major=1))
    violations = registry_mod.check_name_major_unique([e1, e2])
    assert len(violations) == 1
    assert "dup" in violations[0]


def test_check_name_major_unique_allows_same_name_different_major() -> None:
    e1 = RegistryEntry.from_dict(_sample_entry_dict(name="ok", major=1))
    e2 = RegistryEntry.from_dict(_sample_entry_dict(name="ok", major=2))
    assert registry_mod.check_name_major_unique([e1, e2]) == []


def test_check_full_version_major_prefix_mismatch() -> None:
    data = _sample_entry_dict(major=1)
    data["full_version"] = "2.0.0"
    entry = RegistryEntry.from_dict(data)
    violations = registry_mod.check_full_version_major_prefix([entry])
    assert len(violations) == 1
    assert "full_version" in violations[0]


def test_check_full_version_major_prefix_ok() -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict(major=3))
    assert registry_mod.check_full_version_major_prefix([entry]) == []


def test_check_id_category_and_path_mismatch_category() -> None:
    data = _sample_entry_dict(category="domain")
    data["$id"] = (
        "https://schemas.the-saena.ai/context/sample-contract/v1/sample-contract.schema.json"
    )
    entry = RegistryEntry.from_dict(data)
    violations = registry_mod.check_id_category_and_path([entry])
    assert any("category segment" in v for v in violations)


def test_check_id_category_and_path_mismatch_major() -> None:
    data = _sample_entry_dict(major=1)
    data["$id"] = (
        "https://schemas.the-saena.ai/domain/sample-contract/v2/sample-contract.schema.json"
    )
    entry = RegistryEntry.from_dict(data)
    violations = registry_mod.check_id_category_and_path([entry])
    assert any("major segment" in v for v in violations)


def test_check_id_category_and_path_malformed_id() -> None:
    data = _sample_entry_dict()
    data["$id"] = "not-a-valid-id"
    entry = RegistryEntry.from_dict(data)
    violations = registry_mod.check_id_category_and_path([entry])
    assert any("does not match" in v for v in violations)


def test_check_id_category_and_path_ok() -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict())
    assert registry_mod.check_id_category_and_path([entry]) == []


def test_check_schema_file_exists_missing(tmp_path: Path) -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict())
    violations = registry_mod.check_schema_file_exists([entry], contracts_dir=tmp_path)
    assert len(violations) == 1
    assert "missing" in violations[0]


def test_check_schema_file_exists_present(tmp_path: Path) -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict())
    schema_path = registry_mod.schema_file_path_for_entry(entry, contracts_dir=tmp_path)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text("{}", encoding="utf-8")
    assert registry_mod.check_schema_file_exists([entry], contracts_dir=tmp_path) == []


def test_all_relational_violations_combines_all_checks(tmp_path: Path) -> None:
    entry = RegistryEntry.from_dict(_sample_entry_dict())
    violations = registry_mod.all_relational_violations([entry], contracts_dir=tmp_path)
    # schema file missing under tmp_path -> at least that one violation.
    assert any("missing" in v for v in violations)


# --------------------------------------------------------------------------
# Schema validation failure path (synthetic invalid registry document)
# --------------------------------------------------------------------------


def test_validate_registry_document_rejects_invalid_document(tmp_path: Path) -> None:
    schema = registry_mod.load_registry_schema()
    schema_path = tmp_path / "registry.schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    bad_registry = {"registry_version": 1, "contracts": [{"name": "missing-required-fields"}]}
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(bad_registry), encoding="utf-8")

    with pytest.raises(jsonschema.exceptions.ValidationError):
        registry_mod.validate_registry_document(registry_path, schema_path)


def test_load_registry_with_one_valid_synthetic_entry(tmp_path: Path) -> None:
    schema = registry_mod.load_registry_schema()
    schema_path = tmp_path / "registry.schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    document = {"registry_version": 1, "contracts": [_sample_entry_dict()]}
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(document), encoding="utf-8")

    entries = registry_mod.load_registry(registry_path, schema_path)
    assert len(entries) == 1
    assert entries[0].name == "sample-contract"


def test_iter_entries_uses_default_paths() -> None:
    assert registry_mod.iter_entries() == registry_mod.load_registry()
