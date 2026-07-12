"""`GateCheckRequest`'s caller-gap fields (see that dataclass's own
docstring): a `None` value for any policy-gate-REQUIRED field this port
carries fails closed BEFORE any HTTP call — proven here against the real
gate app (so a future fix to the caller-gap that starts sending real values
is what turns these into ordinary allow/deny outcomes, not a change to this
guard itself).
"""

from __future__ import annotations

import pytest
from gate_contract_factories import make_request
from saena_plan_contract.errors import PolicyGateUnavailableError
from saena_plan_contract.gate_client import HttpPolicyGateClient

_REQUIRED_FIELD_OVERRIDES: list[dict[str, object]] = [
    {"proposer_actor_id": None},
    {"approver_actor_id": None},
    {"evidence_ledger_hash": None},
    {"scope_max_globs": None},
    {"diff_max_files": None},
    {"diff_max_lines": None},
]


@pytest.mark.parametrize("overrides", _REQUIRED_FIELD_OVERRIDES)
def test_missing_required_field_fails_closed_before_any_http_call(
    real_gate_client: HttpPolicyGateClient, overrides: dict[str, object]
) -> None:
    request = make_request(contract_hash="sha256:" + "1" * 63 + "a", **overrides)  # type: ignore[arg-type]

    with pytest.raises(PolicyGateUnavailableError, match="missing"):
        real_gate_client.plan_check(request)


def test_all_fields_present_is_not_treated_as_a_caller_gap(
    real_gate_client: HttpPolicyGateClient,
) -> None:
    """Control case: the default `make_request()` carries every field the
    pre-flight guard checks — confirms the guard is precise (fires only on
    an actual `None`), not a blanket refusal."""
    decision = real_gate_client.plan_check(make_request(contract_hash="sha256:" + "2" * 63 + "a"))
    assert decision.allow is True
