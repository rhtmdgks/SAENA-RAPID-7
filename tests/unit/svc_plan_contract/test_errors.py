"""PlanContractError.to_dict() — structured, log-safe representation."""

from __future__ import annotations

from saena_plan_contract.errors import PlanNotFoundError


def test_to_dict_includes_error_code_message_and_context() -> None:
    exc = PlanNotFoundError("no plan found", context={"contract_hash": "sha256:" + "a" * 64})
    result = exc.to_dict()
    assert result["error_code"] == "saena.not_found.resource_missing"
    assert result["message"] == "no plan found"
    assert result["contract_hash"] == "sha256:" + "a" * 64
