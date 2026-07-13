from __future__ import annotations

from hooks_runtime_factories import RUN_ID, TENANT_ID, TRACE_ID, TS, make_budget
from saena_hooks_runtime.hooks.subagent_start import (
    UNTRUSTED_CONTENT_POLICY,
    SubagentStartInput,
    ToolLease,
    subagent_start,
)
from saena_hooks_runtime.models import Decision, ReasonCode


def _input(role: str, lease: ToolLease, **overrides: object) -> SubagentStartInput:
    defaults: dict[str, object] = dict(
        ts=TS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        role=role,
        lease=lease,
        untrusted_content_present=False,
        budget=make_budget("subagent_start"),
    )
    defaults.update(overrides)
    return SubagentStartInput(**defaults)  # type: ignore[arg-type]


def test_writer_with_write_lease_allowed() -> None:
    result = subagent_start(_input("writer", ToolLease(write=True, network=False)))
    assert result.decision == Decision.ALLOW


def test_writer_receiving_read_only_lease_denied() -> None:
    """Task instructions' explicit planted-fixture example: "writer role
    receiving read-only lease"."""
    result = subagent_start(_input("writer", ToolLease(write=False, network=False)))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.WRITER_LEASE_MISMATCH


def test_critic_receiving_write_credentials_denied() -> None:
    """Task instructions' explicit planted-fixture example: "critic role
    receiving write credentials"."""
    result = subagent_start(_input("critic", ToolLease(write=True, network=False)))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.READ_ONLY_ROLE_WRITE_LEASE


def test_reviewer_receiving_write_credentials_denied() -> None:
    result = subagent_start(_input("reviewer", ToolLease(write=True, network=False)))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.READ_ONLY_ROLE_WRITE_LEASE


def test_critic_with_read_only_lease_allowed() -> None:
    result = subagent_start(_input("critic", ToolLease(write=False, network=False)))
    assert result.decision == Decision.ALLOW


def test_browser_unscoped_network_denied() -> None:
    result = subagent_start(
        _input("browser", ToolLease(write=False, network=True, network_targets=()))
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.BROWSER_UNSCOPED_NETWORK


def test_browser_scoped_network_allowed() -> None:
    result = subagent_start(
        _input(
            "browser",
            ToolLease(write=False, network=True, network_targets=("customer-site.example.com",)),
        )
    )
    assert result.decision == Decision.ALLOW


def test_browser_with_write_lease_denied() -> None:
    result = subagent_start(_input("browser", ToolLease(write=True, network=False)))
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.READ_ONLY_ROLE_WRITE_LEASE


def test_untrusted_content_present_injects_policy() -> None:
    result = subagent_start(
        _input("critic", ToolLease(write=False, network=False), untrusted_content_present=True)
    )
    assert result.decision == Decision.ALLOW
    assert result.detail == UNTRUSTED_CONTENT_POLICY


def test_untrusted_content_absent_no_injection() -> None:
    result = subagent_start(
        _input("critic", ToolLease(write=False, network=False), untrusted_content_present=False)
    )
    assert result.detail == ""


def test_timeout_overrun_denies() -> None:
    result = subagent_start(
        _input(
            "writer",
            ToolLease(write=True, network=False),
            budget=make_budget("subagent_start", expired=True),
        )
    )
    assert result.decision == Decision.DENY
    assert result.reason_code == ReasonCode.TIMEOUT_EXCEEDED
