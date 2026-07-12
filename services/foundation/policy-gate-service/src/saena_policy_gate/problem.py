"""RFC 9457 `application/problem+json` error mapping (ADR-0015).

Builds the extended problem-detail shape ADR-0015 confirms (`type`, `title`,
`status`, `detail`, `instance`, plus the SAENA extension fields
`error_code`, `retryable`, `trace_id`, optional `tenant_id`/`run_id`) —
mirrors `saena_schemas.common.problem_detail_v1.ProblemDetail`'s field set
without importing that generated model directly, so this module can build a
plain JSON-serializable `dict` (the FastAPI exception handler's return
shape) without round-tripping through pydantic validation on every error
response.

`type` URIs follow ADR-0015's `https://schemas.the-saena.ai/errors/
<category>/<code>` convention (non-resolvable, same `$id` scheme as
ADR-0011) — `<category>` is the leading segment of `error_code`
(`saena.<category>.<reason>`), `<code>` the trailing segment.
"""

from __future__ import annotations

import uuid
from typing import Any

from saena_policy_gate.errors import PolicyGateError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"


def new_trace_id() -> str:
    """32-hex lowercase W3C-shaped trace id (ADR-0013 envelope `trace_id`
    format, reused verbatim by ADR-0015's `trace_id` problem-detail field)."""
    return uuid.uuid4().hex


def _type_uri(error_code: str) -> str:
    parts = error_code.split(".", 2)
    category = parts[1] if len(parts) > 1 else "internal"
    reason = parts[2] if len(parts) > 2 else "unexpected"
    return f"{_TYPE_BASE}/{category}/{reason}"


def build_problem(
    exc: PolicyGateError,
    *,
    instance: str,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail `dict` from a `PolicyGateError`.

    `detail` carries only `str(exc)` (the exception message) — never
    `exc.context`, which may hold structured values not meant for a public
    detail string; `context` stays server-side/log-only (ADR-0015
    Constraints: no customer source/secret/PII in `detail`).
    """
    problem: dict[str, Any] = {
        "type": _type_uri(exc.error_code),
        "title": exc.__class__.__name__,
        "status": exc.http_status,
        "detail": str(exc),
        "instance": instance,
        "error_code": exc.error_code,
        "retryable": exc.retryable,
        "trace_id": trace_id or new_trace_id(),
    }
    if tenant_id is not None:
        problem["tenant_id"] = tenant_id
    if run_id is not None:
        problem["run_id"] = run_id
    return problem


__all__ = ["build_problem", "new_trace_id"]
