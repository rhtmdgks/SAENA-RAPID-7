"""ChangePlan parsing + patch-unit lookup — `saena_agent_runner.contract`."""

from __future__ import annotations

import pytest
from runner_factories import PATCH_UNIT_ID, build_change_plan
from saena_agent_runner.contract import get_patch_unit, parse_change_plan
from saena_agent_runner.errors import ContractValidationError, PatchUnitNotApprovedError


def test_valid_change_plan_parses() -> None:
    contract = parse_change_plan(build_change_plan())
    assert contract.tenant_id.root == "acme-co"
    assert len(contract.patch_units) == 1


def test_malformed_change_plan_rejected() -> None:
    raw = build_change_plan()
    del raw["approval_required"]
    with pytest.raises(ContractValidationError):
        parse_change_plan(raw)


def test_change_plan_approval_required_must_be_true() -> None:
    raw = build_change_plan()
    raw["approval_required"] = False
    with pytest.raises(ContractValidationError):
        parse_change_plan(raw)


def test_get_patch_unit_returns_named_unit() -> None:
    contract = parse_change_plan(build_change_plan())
    unit = get_patch_unit(contract, PATCH_UNIT_ID)
    assert unit.id == PATCH_UNIT_ID


def test_get_patch_unit_raises_for_unit_not_in_contract() -> None:
    """A patch unit id that is not even a member of the ChangePlan's own
    patch_units is refused — 'execute ONLY the approved patch_units NAMED
    IN THE CONTRACT'."""
    contract = parse_change_plan(build_change_plan())
    with pytest.raises(PatchUnitNotApprovedError):
        get_patch_unit(contract, "PU-does-not-exist")
