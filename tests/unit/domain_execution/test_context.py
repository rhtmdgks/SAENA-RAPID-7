"""JobContext — all 7 fields required, format/non-empty validation."""

from __future__ import annotations

import pytest
from saena_domain.execution.context import JobContext
from saena_domain.execution.errors import JobContextValidationError

VALID_KWARGS = {
    "tenant_id": "acme-co",
    "workspace_id": "ws-0001",
    "project_id": "proj-0001",
    "run_id": "run-2026-0713-0001",
    "trace_id": "a" * 32,
    "idempotency_key": "acme-co:run-2026-0713-0001:unit-01",
    "actor_id": "actor-0001",
}


def test_valid_job_context_constructs() -> None:
    ctx = JobContext(**VALID_KWARGS)
    assert ctx.tenant_id == "acme-co"
    assert ctx.trace_id == "a" * 32


def test_job_context_is_frozen() -> None:
    ctx = JobContext(**VALID_KWARGS)
    with pytest.raises(AttributeError):
        ctx.tenant_id = "other-tenant"  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad_tenant_id",
    ["", "UPPERCASE", "a", "-leading-dash", "trailing-dash-", "a" * 33, "has a space"],
)
def test_invalid_tenant_id_rejected(bad_tenant_id: str) -> None:
    kwargs = {**VALID_KWARGS, "tenant_id": bad_tenant_id}
    with pytest.raises(JobContextValidationError):
        JobContext(**kwargs)


@pytest.mark.parametrize("field_name", ["workspace_id", "project_id", "run_id", "actor_id"])
def test_empty_opaque_identifier_rejected(field_name: str) -> None:
    kwargs = {**VALID_KWARGS, field_name: ""}
    with pytest.raises(JobContextValidationError):
        JobContext(**kwargs)


@pytest.mark.parametrize("field_name", ["workspace_id", "project_id", "run_id", "actor_id"])
def test_oversized_opaque_identifier_rejected(field_name: str) -> None:
    # common/identifiers/v1 maxLength 128
    kwargs = {**VALID_KWARGS, field_name: "x" * 129}
    with pytest.raises(JobContextValidationError):
        JobContext(**kwargs)


@pytest.mark.parametrize("field_name", ["workspace_id", "project_id", "run_id", "actor_id"])
def test_max_length_opaque_identifier_accepted(field_name: str) -> None:
    kwargs = {**VALID_KWARGS, field_name: "x" * 128}
    JobContext(**kwargs)  # must not raise


def test_empty_idempotency_key_rejected() -> None:
    kwargs = {**VALID_KWARGS, "idempotency_key": ""}
    with pytest.raises(JobContextValidationError):
        JobContext(**kwargs)


def test_idempotency_key_has_no_contract_max_length() -> None:
    # event-envelope.schema.json idempotency_key has minLength 1 only, no
    # maxLength — a long composite key must still be accepted.
    kwargs = {**VALID_KWARGS, "idempotency_key": "x" * 1000}
    JobContext(**kwargs)  # must not raise


@pytest.mark.parametrize(
    "bad_trace_id",
    [
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,  # uppercase hex rejected — lowercase only
        "g" * 32,  # not hex
        "not-a-trace-id-at-all-nope-nope",
    ],
)
def test_invalid_trace_id_rejected(bad_trace_id: str) -> None:
    kwargs = {**VALID_KWARGS, "trace_id": bad_trace_id}
    with pytest.raises(JobContextValidationError):
        JobContext(**kwargs)
