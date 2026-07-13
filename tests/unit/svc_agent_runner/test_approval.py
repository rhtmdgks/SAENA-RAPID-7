"""ADR-0003 approval verification — `saena_agent_runner.approval`."""

from __future__ import annotations

import pytest
from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    RUN_ID,
    TENANT_A,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import parse_approval_decision, verify_approval
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.errors import (
    ApprovalContractHashMismatchError,
    ApprovalIdentityMismatchError,
    ApprovalMissingError,
    ApprovalRejectedError,
    ApprovalSignatureInvalidError,
    ContractValidationError,
)


def _contract():
    return parse_change_plan(build_change_plan())


def test_valid_approval_returns_approved_patch_unit_ids() -> None:
    contract = _contract()
    approval = parse_approval_decision(build_approval_decision())
    approved = verify_approval(
        contract=contract,
        approval=approval,
        expected_contract_hash=CONTRACT_HASH,
        expected_tenant_id=TENANT_A,
        expected_run_id=RUN_ID,
    )
    assert approved == frozenset({PATCH_UNIT_ID})


def test_missing_approval_refused() -> None:
    with pytest.raises(ApprovalMissingError):
        parse_approval_decision(None)


def test_unapproved_contract_hash_execution_attempt_refused() -> None:
    """NEGATIVE: an execution attempt whose ApprovalDecision.contract_hash
    does not match the contract actually being executed must be refused."""
    contract = _contract()
    approval = parse_approval_decision(build_approval_decision(contract_hash="sha256:" + "9" * 64))
    with pytest.raises(ApprovalContractHashMismatchError):
        verify_approval(
            contract=contract,
            approval=approval,
            expected_contract_hash=CONTRACT_HASH,
            expected_tenant_id=TENANT_A,
            expected_run_id=RUN_ID,
        )


def test_forged_approval_decision_wrong_shape_rejected() -> None:
    """NEGATIVE: a forged ApprovalDecision (missing required decision field)
    fails structural validation before it is ever handed to verify_approval."""
    raw = build_approval_decision()
    del raw["decision"]
    with pytest.raises(ContractValidationError):
        parse_approval_decision(raw)


def test_forged_approval_decision_missing_signature_rejected() -> None:
    """NEGATIVE: a forged ApprovalDecision missing its signature entirely
    is rejected via the signature-specific error path."""
    raw = build_approval_decision()
    del raw["signature"]
    with pytest.raises(ApprovalSignatureInvalidError):
        parse_approval_decision(raw)


def test_forged_approval_decision_empty_signature_rejected() -> None:
    raw = build_approval_decision(signature="")
    with pytest.raises(ApprovalSignatureInvalidError):
        parse_approval_decision(raw)


def test_rejected_decision_refused() -> None:
    contract = _contract()
    approval = parse_approval_decision(
        build_approval_decision(
            decision="rejected",
            patch_unit_decisions=[{"patch_unit_id": PATCH_UNIT_ID, "decision": "rejected"}],
        )
    )
    with pytest.raises(ApprovalRejectedError):
        verify_approval(
            contract=contract,
            approval=approval,
            expected_contract_hash=CONTRACT_HASH,
            expected_tenant_id=TENANT_A,
            expected_run_id=RUN_ID,
        )


def test_cross_run_replayed_approval_refused() -> None:
    """A structurally-valid approval for a DIFFERENT run must never
    authorize THIS run."""
    contract = _contract()
    approval = parse_approval_decision(build_approval_decision(run_id="run-9999"))
    with pytest.raises(ApprovalIdentityMismatchError):
        verify_approval(
            contract=contract,
            approval=approval,
            expected_contract_hash=CONTRACT_HASH,
            expected_tenant_id=TENANT_A,
            expected_run_id=RUN_ID,
        )


def test_cross_tenant_replayed_approval_refused() -> None:
    contract = _contract()
    approval = parse_approval_decision(build_approval_decision(tenant_id="globex-co"))
    with pytest.raises(ApprovalIdentityMismatchError):
        verify_approval(
            contract=contract,
            approval=approval,
            expected_contract_hash=CONTRACT_HASH,
            expected_tenant_id=TENANT_A,
            expected_run_id=RUN_ID,
        )


def test_patch_unit_individually_rejected_excluded_from_approved_set() -> None:
    contract = build_change_plan(
        patch_units=[
            {
                "id": "PU-01",
                "files": ["a.txt"],
                "allowed_transformations": ["git commit"],
                "tests": ["t"],
                "rollback": "git-revert:PU-01",
            },
            {
                "id": "PU-02",
                "files": ["b.txt"],
                "allowed_transformations": ["git commit"],
                "tests": ["t"],
                "rollback": "git-revert:PU-02",
            },
        ]
    )
    parsed_contract = parse_change_plan(contract)
    approval = parse_approval_decision(
        build_approval_decision(
            patch_unit_decisions=[
                {"patch_unit_id": "PU-01", "decision": "approved"},
                {"patch_unit_id": "PU-02", "decision": "rejected"},
            ]
        )
    )
    approved = verify_approval(
        contract=parsed_contract,
        approval=approval,
        expected_contract_hash=CONTRACT_HASH,
        expected_tenant_id=TENANT_A,
        expected_run_id=RUN_ID,
    )
    assert approved == {"PU-01"}
