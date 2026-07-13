"""packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml composition
proof (w1-11, approved plan §2 "API 문서" AsyncAPI row / §6 "asyncapi" gate;
extended w4-10 Contracts Steward for the 4 Wave 4 NEW channels).

Asserts:
  - channel set == exact 17-channel allowlist (12 CONFIRMED-v1 channels,
    ADR-0013/R4 quality.gate split, + 4 Wave 4 NEW channels --
    entity.graph.versioned.v1/claim.evidence.versioned.v1/
    experiment.registered.v1/experiment.anchored.v1, + 1 Wave 5 NEW channel
    -- deployment.confirmed.v1, w5-02 channel #17).
  - each channel's `event_type` const == its channel address (1:1).
  - exactly 5 channels carry `x-saena-engine-id-required: true` (3
    CONFIRMED-v1 + experiment.registered.v1/experiment.anchored.v1);
    deployment.confirmed.v1 is deliberately NOT among them.
  - every one of the 17 channels' message payload declares
    `schemaFormat: application/schema+json;version=draft-2020-12` (M2
    regression guard -- critic finding that payload MUST be a Multi
    Format Schema Object, not a bare schemaFormat sibling on Message).
  - engine-id glob guard: IF any schema file exists under
    packages/contracts/json-schema/event/{observation-*,citation-*,
    experiment-*}/ THEN its schema MUST allOf-include the engine-id
    engine_required_payload fragment. As of w4-10, 4 such directories now
    exist for real (observation-captured, citation-normalized,
    experiment-registered, experiment-anchored -- all landed with the
    engine_required_payload $ref) -- the guard now runs genuinely, not
    vacuously, on real data; its LOGIC is additionally proven live via a
    synthetic tmp_path fixture that plants a fake matching file and
    asserts the guard fires, so real-data coverage and synthetic-detector
    coverage are both exercised independently.
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
        # Wave 4 NEW channels (w4-10 Contracts Steward,
        # docs/architecture/wave4-plan.md "Existing vs new events").
        "entity.graph.versioned.v1",
        "claim.evidence.versioned.v1",
        "experiment.registered.v1",
        "experiment.anchored.v1",
        # Wave 5 NEW channel (w5-02 Contracts Steward, channel #17 —
        # docs/architecture/wave5-plan.md deliverable 2: the sole 7-day-clock
        # start authority). NOT engine-id-required (deployment confirmation is
        # a customer/CI-CD signal, not a ChatGPT-Search observation).
        "deployment.confirmed.v1",
    }
)

EXPECTED_ENGINE_ID_REQUIRED_CHANNELS: frozenset[str] = frozenset(
    {
        "observation.captured.v1",
        "citation.normalized.v1",
        "experiment.outcome.observed.v1",
        "experiment.registered.v1",
        "experiment.anchored.v1",
    }
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


def test_channel_set_matches_exact_17_allowlist() -> None:
    """12 CONFIRMED-v1 channels + 4 Wave 4 NEW channels (w4-10) + 1 Wave 5 NEW
    channel (w5-02: deployment.confirmed.v1, channel #17) = 17.
    demand.graph.versioned.v1/observation.captured.v1/citation.normalized.v1
    were already among the original 12 and only gained their payload $ref in
    Wave 4; experiment.outcome.observed.v1/strategy.card.eligible.v1 were among
    the original 12 and only gained their payload $ref in Wave 5 -- no
    channel-count change from any of those five."""
    document = _load_yaml(ASYNCAPI_PATH)
    channels = _channels(document)
    actual_addresses = {ch["address"] for ch in channels.values()}
    assert actual_addresses == EXPECTED_CHANNEL_ADDRESSES, (
        f"channel set mismatch: missing={EXPECTED_CHANNEL_ADDRESSES - actual_addresses}, "
        f"extra={actual_addresses - EXPECTED_CHANNEL_ADDRESSES}"
    )
    assert len(channels) == 17


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


def test_exactly_5_channels_require_engine_id() -> None:
    """3 CONFIRMED-v1 engine-required channels + 2 Wave 4 NEW engine-required
    channels (experiment.registered.v1/experiment.anchored.v1 -- ADR-0013
    'observation·citation·experiment 계열' rule covers the whole family,
    including the registration/anchor notifications) = 5. Wave 5's new
    deployment.confirmed.v1 is deliberately NOT in this set (deployment
    confirmation is a customer/CI-CD signal, not a ChatGPT-Search observation
    -- wave5-plan.md deliverable 2), so the count stays 5, not 6."""
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
    assert len(flagged) == 5


def test_deployment_confirmed_is_not_engine_id_required() -> None:
    """Explicit guard (wave5-plan.md deliverable 2): deployment.confirmed.v1 is
    a customer/CI-CD deployment signal, NOT a per-engine observation, so it must
    NOT carry x-saena-engine-id-required. A future accidental addition of that
    flag (which would wrongly force an engine_id into the deployment signal)
    fails here loudly, independent of the exact-set assertion above."""
    document = _load_yaml(ASYNCAPI_PATH)
    channels = _channels(document)
    deployment = channels["deployment.confirmed.v1"]
    assert "x-saena-engine-id-required" not in deployment, (
        "deployment.confirmed.v1 must NOT declare x-saena-engine-id-required "
        "(it is not an engine observation)"
    )
    assert "deployment.confirmed.v1" not in EXPECTED_ENGINE_ID_REQUIRED_CHANNELS


def test_all_17_channels_use_draft_2020_12_schema_format() -> None:
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


def test_engine_id_glob_guard_passes_genuinely_on_current_catalog() -> None:
    """w4-10: observation-captured, citation-normalized, experiment-registered,
    and experiment-anchored payload schema files now exist for real (all 4
    were envelope-only P1-deferred/not-yet-landed pre-Wave-4) and each
    allOf-includes the engine_required_payload fragment -- the guard must
    pass with zero violations GENUINELY (not vacuously) on real data.
    """
    event_dir = CONTRACTS_JSON_SCHEMA_DIR / "event"
    violations = find_engine_family_schemas_missing_engine_id_fragment(event_dir)
    assert violations == [], f"unexpected engine-family guard violations: {violations}"


def test_engine_family_schema_directories_match_expected_set() -> None:
    """Meta-assertion documenting exactly which observation-*/citation-*/
    experiment-* directories exist -- if this set ever drifts (a new
    engine-family contract lands, or one is renamed/removed), this fails
    loudly rather than the guard above silently covering an unexpected set.
    w5-02 adds experiment-outcome-observed (an experiment-family event that
    IS engine-id-required and correctly includes the engine_required_payload
    fragment). Note: deployment-confirmed does NOT match these prefixes and is
    (correctly) absent -- it is not engine-id-required.
    """
    event_dir = CONTRACTS_JSON_SCHEMA_DIR / "event"
    matching = {
        d.name
        for d in event_dir.iterdir()
        if d.is_dir() and d.name.startswith(_ENGINE_FAMILY_PREFIXES)
    }
    assert matching == {
        "observation-captured",
        "citation-normalized",
        "experiment-registered",
        "experiment-anchored",
        # w5-02 (Wave 5): experiment-family, engine-id-required.
        "experiment-outcome-observed",
    }, f"engine-family directory set drifted from expectations: {matching}"


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
