"""RFC 9457 `application/problem+json` response builder (ADR-0015).

Shapes any `EngineGatewayError` into the
`packages/contracts/json-schema/common/problem-detail/v1/problem-detail.schema.json`
fields: 5 RFC 9457 standard fields (`type`, `title`, `status`, `detail`,
`instance`) plus SAENA's 4 extension fields (`error_code`, `retryable`,
`trace_id`, optional `tenant_id`/`run_id`). `detail` never carries customer
source, secrets, or PII (ADR-0015 Constraints) — every `EngineGatewayError`
subclass's `context` in this package is already limited to engine_id /
adapter-key strings, so `str(exc)` is safe to use verbatim as `detail`.
"""

from __future__ import annotations

from typing import Any

from saena_observability.trace import current_trace_id, generate_trace_id

from saena_engine_gateway.errors import EngineGatewayError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"


def build_problem_detail(
    exc: EngineGatewayError,
    *,
    instance: str,
    tenant_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail body for `exc`.

    `trace_id` is read from the currently bound OTel span context
    (`saena_observability.trace.current_trace_id`) when available, falling
    back to a freshly generated 32-hex id — the field is required by the
    contract and must never be omitted even outside a traced request.
    """
    trace_id = current_trace_id() or generate_trace_id()
    category = exc.error_code.split(".")[1] if "." in exc.error_code else "internal"
    body: dict[str, Any] = {
        "type": f"{_TYPE_BASE}/{category}/{exc.error_code}",
        "title": exc.__class__.__name__,
        "status": exc.http_status,
        "detail": str(exc),
        "instance": instance,
        "error_code": exc.error_code,
        "retryable": exc.retryable,
        "trace_id": trace_id,
    }
    if tenant_id is not None:
        body["tenant_id"] = tenant_id
    if run_id is not None:
        body["run_id"] = run_id
    return body
