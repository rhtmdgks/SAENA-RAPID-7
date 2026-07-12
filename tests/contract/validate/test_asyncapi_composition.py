"""packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml composition
proof (w1-11, approved plan §2 "API 문서" AsyncAPI row / §6 "asyncapi" gate).

Asserts:
  - channel set == exact 12-channel allowlist (CONFIRMED v1 event catalog,
    ADR-0013/R4 quality.gate split).
  - each channel's `event_type` const == its channel address (1:1).
  - exactly 3 channels carry `x-saena-engine-id-required: true`.
  - every one of the 12 channels' message payload declares
    `schemaFormat: application/schema+json;version=draft-2020-12` (M2
    regression guard -- critic finding that payload MUST be a Multi
    Format Schema Object, not a bare schemaFormat sibling on Message).
  - engine-id glob guard: IF any schema file exists under
    packages/contracts/json-schema/event/{observation-*,citation-*,
    experiment-*}/ THEN its schema MUST allOf-include the engine-id
    engine_required_payload fragment. Currently zero such files exist
    (all three are envelope-only P1-deferred channels per the AsyncAPI
    doc's own channel descriptions) -- the guard passes trivially on
    real data, but its LOGIC is proven live via a synthetic tmp_path
    fixture that plants a fake matching file and asserts the guard
    fires, so an empty-glob pass here can never be mistaken for the
    guard function being untested.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTRACTS_JSON_SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "json-schema"
ASYNCAPI_PATH = (
    REPO_ROOT / "packages" / "contracts" / "asyncapi" / "saena-events" / "v1" / "asyncapi.yaml"
)

EXPECTED_CHANNEL_ADDRESSES: frozenset[str] = frozenset(
    {
        "repo.intaken.v1",
        "site.inventory.completed.v1",
        "demand.graph.versioned.v1",
        "observation.captured.v1",
        "citation.normalized.v1",
        "plan.contract.proposed.v1",
        "plan.contract.approved.v1",
        "patch.unit.completed.v1",
        "quality.gate.passed.v1",
        "quality.gate.failed.v1",
        "experiment.outcome.observed.v1",
        "strategy.card.eligible.v1",
    }
)

EXPECTED_ENGINE_ID_REQUIRED_CHANNELS: frozenset[str] = frozenset(
    {"observation.captured.v1", "citation.normalized.v1", "experiment.outcome.observed.v1"}
)

EXPECTED_SCHEMA_FORMAT = "application/schema+json;version=draft-2020-12"

# ADR-0013 activation-fragment convention: an engine-required payload
# schema allOf-includes the engine-id $defs.engine_required_payload
# fragment via $ref (see common/engine-id/v1's own $comment describing
# this fragment's purpose).
ENGINE_REQUIRED_PAYLOAD_REF_SUFFIX = (
    "engine-id/v1/engine-id.schema.json#/$defs/engine_required_payload"
)

# The 3 event-family directory-name globs the guard watches (per the
# plan's own wording: "observation-*,citation-*,experiment-*").
_ENGINE_FAMILY_PREFIXES = ("observation-", "citation-", "experiment-")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _channels(document: dict[str, Any]) -> dict[str, Any]:
    return document["channels"]


def _message_payload(channel: dict[str, Any]) -> dict[str, Any]:
    messages = channel["messages"]
    # Exactly one message per channel in this catalog (verified by the
    # count assertion in test_each_channel_has_exactly_one_message).
    (message,) = messages.values()
    return message["payload"]


def test_asyncapi_file_exists() -> None:
    assert ASYNCAPI_PATH.is_file(), f"asyncapi.yaml missing at {ASYNCAPI_PATH}"


def test_asyncapi_parses_as_yaml() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    assert document.get("asyncapi", "").startswith("3.0")


def test_channel_set_matches_exact_12_allowlist() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    channels = _channels(document)
    actual_addresses = {ch["address"] for ch in channels.values()}
    assert actual_addresses == EXPECTED_CHANNEL_ADDRESSES, (
        f"channel set mismatch: missing={EXPECTED_CHANNEL_ADDRESSES - actual_addresses}, "
        f"extra={actual_addresses - EXPECTED_CHANNEL_ADDRESSES}"
    )
    assert len(channels) == 12


def test_each_channel_has_exactly_one_message() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    for name, channel in _channels(document).items():
        assert len(channel["messages"]) == 1, f"{name}: expected exactly 1 message"


def test_event_type_const_matches_channel_address_1_to_1() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    for name, channel in _channels(document).items():
        payload = _message_payload(channel)
        all_of = payload["schema"]["allOf"]
        overlay = next(branch for branch in all_of if "properties" in branch)
        event_type_const = overlay["properties"]["event_type"]["const"]
        assert event_type_const == channel["address"], (
            f"{name}: event_type const {event_type_const!r} != channel address "
            f"{channel['address']!r}"
        )


def test_exactly_3_channels_require_engine_id() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    channels = _channels(document)
    flagged = {
        name for name, ch in channels.items() if ch.get("x-saena-engine-id-required") is True
    }
    flagged_addresses = {channels[name]["address"] for name in flagged}
    assert flagged_addresses == EXPECTED_ENGINE_ID_REQUIRED_CHANNELS, (
        f"x-saena-engine-id-required channel set mismatch: {flagged_addresses} != "
        f"{EXPECTED_ENGINE_ID_REQUIRED_CHANNELS}"
    )
    assert len(flagged) == 3


def test_all_12_channels_use_draft_2020_12_schema_format() -> None:
    """M2 regression guard: every message payload must be a Multi Format
    Schema Object (payload.schemaFormat + payload.schema), schemaFormat
    pinned to draft-2020-12 -- not a bare sibling key on Message.
    """
    document = _load_yaml(ASYNCAPI_PATH)
    for name, channel in _channels(document).items():
        payload = _message_payload(channel)
        assert payload.get("schemaFormat") == EXPECTED_SCHEMA_FORMAT, (
            f"{name}: payload.schemaFormat != {EXPECTED_SCHEMA_FORMAT!r}, got "
            f"{payload.get('schemaFormat')!r}"
        )
        assert "schema" in payload, (
            f"{name}: payload missing 'schema' key (Multi Format Schema Object)"
        )


def test_every_message_payload_allof_refs_the_envelope() -> None:
    document = _load_yaml(ASYNCAPI_PATH)
    for name, channel in _channels(document).items():
        payload = _message_payload(channel)
        all_of = payload["schema"]["allOf"]
        envelope_ref = all_of[0].get("$ref", "")
        assert envelope_ref.endswith("event-envelope/v1/event-envelope.schema.json"), (
            f"{name}: expected the first allOf branch to $ref the envelope, got {envelope_ref!r}"
        )


# --------------------------------------------------------------------------
# Engine-id glob guard (proven live via synthetic tmp_path fixture).
# --------------------------------------------------------------------------


def find_engine_family_schemas_missing_engine_id_fragment(
    event_dir: Path,
) -> list[str]:
    """Scan `event_dir` (packages/contracts/json-schema/event/) for any
    contract directory whose name starts with one of the 3 engine-required
    family prefixes (observation-, citation-, experiment-) and return a
    list of violation strings for every such contract's schema file that
    does NOT allOf-include the engine-id engine_required_payload fragment
    ref. Empty list = guard passes (vacuously, if no matching directories
    exist yet, or genuinely, if every matching schema includes the
    fragment).
    """
    violations: list[str] = []
    if not event_dir.is_dir():
        return violations
    for contract_dir in sorted(event_dir.iterdir()):
        if not contract_dir.is_dir():
            continue
        if not contract_dir.name.startswith(_ENGINE_FAMILY_PREFIXES):
            continue
        schema_files = list(contract_dir.glob("v*/*.schema.json"))
        for schema_file in schema_files:
            text = schema_file.read_text(encoding="utf-8")
            if ENGINE_REQUIRED_PAYLOAD_REF_SUFFIX not in text:
                violations.append(
                    f"{schema_file}: engine-family contract missing engine_required_payload "
                    "$ref (ADR-0013 engine-id activation fragment)"
                )
    return violations


def test_engine_id_glob_guard_passes_trivially_on_current_catalog() -> None:
    """No observation-*/citation-*/experiment-* payload schema files exist
    yet (all 3 are envelope-only P1-deferred channels) -- the guard must
    pass with zero violations, not error out on an empty glob.
    """
    event_dir = CONTRACTS_JSON_SCHEMA_DIR / "event"
    violations = find_engine_family_schemas_missing_engine_id_fragment(event_dir)
    assert violations == [], f"unexpected engine-family guard violations: {violations}"


def test_no_engine_family_schema_directories_exist_yet() -> None:
    """Meta-assertion documenting WHY the guard above passes trivially --
    if this ever starts failing (a real observation-*/citation-*/
    experiment-* directory landed), the guard above stops being trivial
    and must be re-verified against real content, not silently trusted.
    """
    event_dir = CONTRACTS_JSON_SCHEMA_DIR / "event"
    matching = [
        d for d in event_dir.iterdir() if d.is_dir() and d.name.startswith(_ENGINE_FAMILY_PREFIXES)
    ]
    assert matching == [], (
        f"found engine-family directories the guard's 'trivial pass' assumption did not "
        f"account for: {matching}"
    )


def test_engine_id_glob_guard_fires_on_synthetic_missing_fragment(tmp_path: Path) -> None:
    """Plants a fake `event/observation-captured/v1/observation-captured.schema.json`
    under a synthetic event_dir that does NOT include the engine_required_payload
    $ref, and asserts the guard function actually flags it -- proves the
    guard's detection logic is live, not just vacuously green because no
    real directory matches yet.
    """
    event_dir = tmp_path / "event"
    contract_dir = event_dir / "observation-captured" / "v1"
    contract_dir.mkdir(parents=True)
    schema_file = contract_dir / "observation-captured.schema.json"
    schema_file.write_text(
        '{"$schema": "https://json-schema.org/draft/2020-12/schema", '
        '"$id": "https://schemas.the-saena.ai/event/observation-captured/v1/'
        'observation-captured.schema.json", "type": "object"}',
        encoding="utf-8",
    )

    violations = find_engine_family_schemas_missing_engine_id_fragment(event_dir)
    assert violations, "expected the guard to flag the synthetic missing-fragment schema"
    assert "observation-captured.schema.json" in violations[0]


def test_engine_id_glob_guard_passes_on_synthetic_compliant_fragment(tmp_path: Path) -> None:
    """Companion positive case: a synthetic engine-family schema that DOES
    include the fragment ref must NOT be flagged.
    """
    event_dir = tmp_path / "event"
    contract_dir = event_dir / "citation-normalized-detail" / "v1"
    contract_dir.mkdir(parents=True)
    schema_file = contract_dir / "citation-normalized-detail.schema.json"
    schema_file.write_text(
        '{"$schema": "https://json-schema.org/draft/2020-12/schema", '
        '"$id": "https://schemas.the-saena.ai/event/citation-normalized-detail/v1/'
        'citation-normalized-detail.schema.json", "allOf": [{"$ref": '
        '"../../../common/engine-id/v1/engine-id.schema.json#/$defs/engine_required_payload"}]}',
        encoding="utf-8",
    )

    violations = find_engine_family_schemas_missing_engine_id_fragment(event_dir)
    assert violations == [], f"expected no violations, got: {violations}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
