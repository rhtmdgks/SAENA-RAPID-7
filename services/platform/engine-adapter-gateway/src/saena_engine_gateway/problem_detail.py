"""RFC 9457 `application/problem+json` response builder (ADR-0015).

Shapes errors into the
`packages/contracts/json-schema/common/problem-detail/v1/problem-detail.schema.json`
fields: 5 RFC 9457 standard fields (`type`, `title`, `status`, `detail`,
`instance`) plus SAENA's 4 extension fields (`error_code`, `retryable`,
`trace_id`, optional `tenant_id`/`run_id`). `detail` never carries customer
source, secrets, or PII (ADR-0015 Constraints).

Two builders:

- `build_problem_detail` — for `EngineGatewayError` subclasses. Every
  subclass's `context` in this package is already limited to engine_id /
  adapter-key strings, so `str(exc)` is safe to use verbatim as `detail`.
- `build_generic_problem_detail` — for errors this package does not
  construct itself (FastAPI's `RequestValidationError`, and any other
  unexpected `Exception`). Callers pass a fixed, pre-approved `detail`
  string rather than `str(exc)` here — the whole point of this builder is
  to guarantee no attacker-controlled or framework-echoed value (e.g.
  pydantic-core's `input` field on a validation error, or an exception's
  own `args`) ever reaches the response body (critic MUST-FIX 1: the
  default FastAPI `RequestValidationError` handler echoes the raw rejected
  value via `errors()[i]["input"]`, and a bare `str(exc)` on an arbitrary
  `Exception` is a stack-trace/internal-detail leak risk — ADR-0015
  Constraints already forbid customer source/secrets/PII in `detail`, and
  an uncontrolled `Exception` message cannot be proven to satisfy that).
"""

from __future__ import annotations

from typing import Any

from saena_observability.trace import current_trace_id, generate_trace_id

from saena_engine_gateway.errors import EngineGatewayError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"


def _resolve_trace_id() -> str:
    """`trace_id` is read from the currently bound OTel span context
    (`saena_observability.trace.current_trace_id`) when available, falling
    back to a freshly generated 32-hex id — the field is required by the
    contract and must never be omitted even outside a traced request."""
    return current_trace_id() or generate_trace_id()


def build_problem_detail(
    exc: EngineGatewayError,
    *,
    instance: str,
    tenant_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail body for `exc`."""
    category = exc.error_code.split(".")[1] if "." in exc.error_code else "internal"
    return _assemble(
        type_=f"{_TYPE_BASE}/{category}/{exc.error_code}",
        title=exc.__class__.__name__,
        status=exc.http_status,
        detail=str(exc),
        instance=instance,
        error_code=exc.error_code,
        retryable=exc.retryable,
        tenant_id=tenant_id,
        run_id=run_id,
    )


def build_generic_problem_detail(
    *,
    title: str,
    status: int,
    detail: str,
    error_code: str,
    instance: str,
    retryable: bool = False,
    tenant_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail body from fixed, pre-approved
    fields — no exception object, no `str(exc)`, no framework-supplied
    `errors()` payload.

    Callers (`app.py`'s `RequestValidationError`/generic-`Exception`
    handlers) must pass a `detail` string that is a static literal or
    otherwise proven free of request-derived content — this function does
    not itself sanitize `detail`, it just refuses to source one from
    anywhere unsafe on the caller's behalf.
    """
    category = error_code.split(".")[1] if "." in error_code else "internal"
    return _assemble(
        type_=f"{_TYPE_BASE}/{category}/{error_code}",
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        error_code=error_code,
        retryable=retryable,
        tenant_id=tenant_id,
        run_id=run_id,
    )


def _assemble(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str,
    instance: str,
    error_code: str,
    retryable: bool,
    tenant_id: str | None,
    run_id: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "error_code": error_code,
        "retryable": retryable,
        "trace_id": _resolve_trace_id(),
    }
    if tenant_id is not None:
        body["tenant_id"] = tenant_id
    if run_id is not None:
        body["run_id"] = run_id
    return body
