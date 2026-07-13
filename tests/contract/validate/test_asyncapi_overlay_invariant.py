"""AsyncAPI allOf-overlay STRUCTURAL invariant (w1-11 critic MUST-1 rework).

Ruling R8 (approved plan §1.1: "AsyncAPI allOf-overlay 유효 확정 -- 단
overlay 불변식 meta-test('overlay 키 ⊆ 각 분기 properties') + codegen spike에
조합 인스턴스 검증 추가") requires a dedicated STRUCTURAL meta-test,
independent of `test_composition_instances.py`'s instance-level
composition proofs. An instance-level proof only shows that ONE crafted
instance happens to satisfy the overlay for whichever envelope branch that
instance picked (`context_type`) -- it cannot, by construction, prove the
overlay's own `properties` key set is safe for the branches that
instance's particular choice never exercises. A future overlay
regression (e.g. someone adds an optional key to a channel's overlay
that only exists on the `tenant` branch, while that channel's
`context_type` const happens to be `aggregate`) would silently produce
an overlay that is unsatisfiable for its own declared context_type, or
worse, one that leaks a branch-specific field into a schema shape that
looks valid for instances of a DIFFERENT branch -- neither failure mode
is guaranteed to be caught by a single hand-picked instance fixture.

This module instead does a purely STRUCTURAL check: for each of the 17
channels (12 CONFIRMED-v1 + 4 Wave 4 NEW, w4-10 Contracts Steward),
extract the overlay's (`allOf[1]`) `properties` key set and assert it is
a SUBSET of each of the envelope's 3 `$defs` oneOf branches'
(`tenantContextEnvelope`, `systemContextEnvelope`,
`aggregateContextEnvelope`) own `properties` key sets -- i.e. the overlay
never declares a property name that is not already envelope-branch
vocabulary in EVERY branch, regardless of which one instance validation
would ultimately pick. This statically blocks the regression class
described above without needing to construct or validate any instance at
all.

Non-vacuousness proof: `test_overlay_subset_check_fails_on_synthetic_bad_overlay`
plants a synthetic overlay containing a key
("mutant_out_of_branch_key") absent from every envelope branch and
asserts the checker function actually flags it.
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
ENVELOPE_SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR / "envelope" / "event-envelope" / "v1" / "event-envelope.schema.json"
)

ENVELOPE_ONE_OF_BRANCH_NAMES: tuple[str, ...] = (
    "tenantContextEnvelope",
    "systemContextEnvelope",
    "aggregateContextEnvelope",
)

ALL_CHANNEL_NAMES: tuple[str, ...] = (
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
    # Wave 4 NEW channels (w4-10 Contracts Steward).
    "entity.graph.versioned.v1",
    "claim.evidence.versioned.v1",
    "experiment.registered.v1",
    "experiment.anchored.v1",
    # Wave 5 NEW channel (w5-02 Contracts Steward, channel #17).
    "deployment.confirmed.v1",
)


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def envelope_branch_property_keysets(schema: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Return {branch_name: frozenset(properties.keys())} for each of the
    3 envelope $defs oneOf branches.
    """
    defs = schema["$defs"]
    return {
        branch_name: frozenset(defs[branch_name]["properties"].keys())
        for branch_name in ENVELOPE_ONE_OF_BRANCH_NAMES
    }


def channel_overlay_property_keys(channel: dict[str, Any]) -> frozenset[str]:
    """Extract the overlay branch (the allOf element carrying a
    `properties` key -- i.e. NOT the `$ref` to the envelope schema) of one
    channel's message payload.schema, and return its `properties` key set.
    """
    (message,) = channel["messages"].values()
    all_of = message["payload"]["schema"]["allOf"]
    overlay = next(branch for branch in all_of if "properties" in branch)
    return frozenset(overlay["properties"].keys())


def find_overlay_keys_outside_any_branch(
    overlay_keys: frozenset[str], branch_keysets: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    """For each envelope branch, return the overlay keys NOT present in
    that branch's own properties key set. A channel's overlay is
    structurally sound (R8 invariant) only if this returns an
    ALL-EMPTY mapping for every branch -- i.e. overlay_keys is a subset
    of EVERY branch's properties, not just the branch the channel
    happens to declare via context_type const.
    """
    return {
        branch_name: overlay_keys - branch_keys
        for branch_name, branch_keys in branch_keysets.items()
        if overlay_keys - branch_keys
    }


def test_envelope_has_exactly_3_oneof_branches() -> None:
    """Meta-precondition: the envelope's $defs must still carry all 3
    named branches this module hardcodes -- if the envelope schema is
    ever restructured, this fails loudly instead of the branch lookup
    silently returning nothing everywhere below.
    """
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    defs = schema["$defs"]
    for branch_name in ENVELOPE_ONE_OF_BRANCH_NAMES:
        assert branch_name in defs, f"envelope $defs missing expected branch {branch_name!r}"


@pytest.mark.parametrize("channel_name", ALL_CHANNEL_NAMES)
def test_overlay_properties_are_subset_of_every_envelope_branch(channel_name: str) -> None:
    """The R8 structural invariant itself: overlay properties keys ⊆
    EVERY envelope oneOf branch's properties keys, for all 17 channels.
    """
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    branch_keysets = envelope_branch_property_keysets(schema)

    asyncapi_doc = _load_yaml(ASYNCAPI_PATH)
    channel = asyncapi_doc["channels"][channel_name]
    overlay_keys = channel_overlay_property_keys(channel)

    violations = find_overlay_keys_outside_any_branch(overlay_keys, branch_keysets)
    assert not violations, (
        f"{channel_name}: overlay properties {sorted(overlay_keys)} are not a subset of every "
        f"envelope branch's properties -- out-of-branch keys per branch: "
        f"{ {k: sorted(v) for k, v in violations.items()} }"
    )


def test_overlay_subset_check_covers_all_17_channels() -> None:
    """Meta-test: prove the parametrized check above actually iterates all
    17 channels, not a truncated/typo'd subset.
    """
    asyncapi_doc = _load_yaml(ASYNCAPI_PATH)
    actual_channel_names = frozenset(asyncapi_doc["channels"].keys())
    assert actual_channel_names == frozenset(ALL_CHANNEL_NAMES), (
        f"channel name set mismatch: {actual_channel_names} != {frozenset(ALL_CHANNEL_NAMES)}"
    )


# --------------------------------------------------------------------------
# Non-vacuousness proof: the checker function must actually FAIL on a
# synthetic overlay carrying an out-of-branch key.
# --------------------------------------------------------------------------


def test_overlay_subset_check_fails_on_synthetic_bad_overlay() -> None:
    """Plants a synthetic overlay properties key set containing
    'mutant_out_of_branch_key' -- a name absent from every real envelope
    branch -- and asserts `find_overlay_keys_outside_any_branch` actually
    flags it against every branch. Proves the checker is a live detector,
    not a function that only happens to pass because the real document is
    already correct.
    """
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    branch_keysets = envelope_branch_property_keysets(schema)

    synthetic_overlay_keys = frozenset({"context_type", "event_type", "mutant_out_of_branch_key"})
    violations = find_overlay_keys_outside_any_branch(synthetic_overlay_keys, branch_keysets)

    assert violations, "expected the synthetic bad overlay to be flagged but got no violations"
    assert len(violations) == len(ENVELOPE_ONE_OF_BRANCH_NAMES), (
        f"expected all {len(ENVELOPE_ONE_OF_BRANCH_NAMES)} branches to report the mutant key, "
        f"got violations for: {sorted(violations)}"
    )
    for branch_name, missing_keys in violations.items():
        assert missing_keys == frozenset({"mutant_out_of_branch_key"}), (
            f"{branch_name}: expected only the mutant key to be flagged, got {sorted(missing_keys)}"
        )


def test_overlay_subset_check_passes_on_synthetic_good_overlay() -> None:
    """Companion positive case: an overlay using only keys common to all
    3 branches (context_type, event_type, payload -- verified common
    vocabulary by test_overlay_properties_are_subset_of_every_envelope_branch
    passing for real data) must NOT be flagged.
    """
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    branch_keysets = envelope_branch_property_keysets(schema)

    synthetic_overlay_keys = frozenset({"context_type", "event_type", "payload"})
    violations = find_overlay_keys_outside_any_branch(synthetic_overlay_keys, branch_keysets)

    assert violations == {}, f"expected no violations for a common-vocabulary overlay: {violations}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
