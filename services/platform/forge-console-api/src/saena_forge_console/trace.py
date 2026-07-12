"""W3C `traceparent` accept/generate + response-header propagation (ADR-0016).

`trace_middleware` is the outermost middleware in the stack (registered
last, so it runs first — see `saena_forge_console.app`): it resolves this
request's `trace_id`/`span_id` from an inbound `traceparent` header (parsed
via `saena_observability.trace.parse_traceparent`) or generates a fresh pair
when absent/malformed, stashes them on `request.state` for every downstream
handler/dependency to read (`resolve_trace_id` below), and always writes the
resolved `traceparent` back onto the RESPONSE headers — so a caller that
sent no header still gets one back, and 3-way correlation (trace/log/event,
ADR-0016 "상관관계" row) works even for a client that only reads response
headers rather than propagating a header of its own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from saena_observability.trace import (
    build_traceparent,
    generate_span_id,
    generate_trace_id,
    parse_traceparent,
)

TRACEPARENT_HEADER = "traceparent"

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


def resolve_trace_id(request: Request) -> str:
    """Read the `trace_id` `trace_middleware` already bound onto
    `request.state`. Falls back to generating a fresh one if called before
    the middleware ran (defensive — every route in this service passes
    through the middleware in normal operation, but exception handlers that
    fire before middleware attaches state, e.g. a malformed request FastAPI
    itself rejects, must not crash trying to read an unset attribute)."""
    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str):
        return trace_id
    return generate_trace_id()


async def trace_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    header_value = request.headers.get(TRACEPARENT_HEADER)
    trace_id: str
    span_id: str
    if header_value is not None:
        try:
            parsed = parse_traceparent(header_value)
            trace_id, span_id = parsed.trace_id, generate_span_id()
        except ValueError:
            trace_id, span_id = generate_trace_id(), generate_span_id()
    else:
        trace_id, span_id = generate_trace_id(), generate_span_id()

    request.state.trace_id = trace_id
    request.state.span_id = span_id

    response = await call_next(request)
    response.headers[TRACEPARENT_HEADER] = build_traceparent(trace_id, span_id)
    return response


__all__ = ["TRACEPARENT_HEADER", "resolve_trace_id", "trace_middleware"]
