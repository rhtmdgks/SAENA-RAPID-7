"""audit-ledger-service FastAPI app — append-only hash-chain API + lineage RBAC.

Spec basis: `services/foundation/audit-ledger-service/README.md`
("append-only run/event/hash chain; immutable role access"),
`docs/architecture/contract-catalog.md` AuditEvent row, ADR-0013
(`lineage_audit_ref` audit-role-only), ADR-0015 (canonical error model /
`AuditEvent` error footprint), and the merged w2 runtime: `saena_domain.audit`
(`build_entry`/`verify_chain`/`make_lineage_ref`/`guard_payload`),
`saena_domain.persistence.AuditLedgerPort`, `saena_domain.authz`
(`Role`/`Permission`/`authorize`, default-deny, `view_lineage` auditor-only).

Append-only semantics (README "immutable role access"): this router declares
NO update/delete route for `/v1/audit/entries` at all — there is no handler
signature anywhere in this module capable of mutating or removing an
already-appended entry. `test_no_update_delete_routes_exist` (services layer
test) asserts this by inspecting the FastAPI route table rather than merely
probing a few methods, so a future edit cannot silently reintroduce a
mutation route without the test catching it.

Value-echo hardening (critic MUST-FIX 1/2, w2-10 review): two global
exception handlers replace FastAPI's defaults — `RequestValidationError`
(malformed/wrong-type request bodies) and a catch-all `Exception` (500) — so
that EVERY error response this service returns is `application/problem+json`
and NEVER echoes a raw caller-supplied value or a stack trace (see
`problem.py`'s "Value-echo hardening" docstring). `AppendEntryRequest.
error_code` is guarded via `saena_domain.audit.guard_payload` BEFORE
`build_entry` is called (`build_entry` itself only guards `payload`/`actor`,
never `error_code`) — a caller-supplied `error_code` containing
guard-detectable content (e.g. a stack-trace fragment) is rejected exactly
like a forbidden `payload` key, value never echoed.

`audit.event.appended.v1` is a PROPOSED topic (README "Published events" row)
— no outbox publish happens here (W2A scope note, `saena_domain.persistence.
ports` module docstring: "이벤트는 transactional outbox 기록까지 — bus 배선은
2C", and this service does not yet call `OutboxPort` for this topic since
the topic itself is not yet CONFIRMED). Every successful append instead emits
one structured log line via `saena_observability.get_logger` documenting the
event was appended — this is intentionally NOT a substitute for the future
outbox publish, only an operational breadcrumb for W2A.

AuthN boundary (documented, not fixed here): caller roles are read from the
`X-Saena-Roles` header (`authz_boundary.roles_from_header`) — nothing in this
process verifies the header's claims against a real identity (mTLS cert,
JWT, session). Real authN is W3+ scope. What IS real: the RBAC decision
itself, `saena_domain.authz.authorize`'s default-deny allow matrix — a
request with no roles, or with roles that do not carry the required
permission, is rejected exactly as it would be against a verified identity.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from saena_domain.audit import ForbiddenAuditDataError, guard_payload, make_lineage_ref

# `build_entry`/`is_lineage_ref` are not re-exported from `saena_domain.audit`'s
# `__all__` (see that package's `__init__.py`) — imported from their owning
# submodules directly. `packages/domain` is read-only for this patch unit, so
# this is the only available import path rather than a stylistic choice.
from saena_domain.audit.chain import build_entry
from saena_domain.audit.lineage import is_lineage_ref
from saena_domain.authz import Permission
from saena_domain.identity import TENANT_HEADER_NAME, InvalidTenantIdError, TenantId
from saena_domain.identity.errors import IdentityError
from saena_domain.persistence import AuditLedgerPort
from saena_domain.persistence.errors import PersistenceError
from saena_observability import get_logger

from saena_audit_ledger.authz_boundary import has_permission
from saena_audit_ledger.problem import (
    bad_request_problem,
    domain_error_problem,
    forbidden_audit_data_problem,
    forbidden_rbac_problem,
    internal_error_problem,
    not_found_problem,
    problem_response,
    validation_error_problem,
)
from saena_audit_ledger.schemas import (
    AppendEntryRequest,
    EntryListResponse,
    EntryResponse,
    VerifyResponse,
)

_logger = get_logger("saena.audit_ledger")

_APPENDED_LOG_ACTION = "audit.event.appended.v1"


def _parse_tenant_header(request: Request) -> TenantId | None:
    """Read `X-Saena-Tenant-Id` (ADR-0014) and return a validated `TenantId`,
    or `None` when absent (system-scope requests carry no tenant header).

    Raises `InvalidTenantIdError` (mapped to 400 by the caller) if the header
    is present but does not match the ADR-0014 slug pattern — never silently
    dropped or coerced.
    """
    raw = request.headers.get(TENANT_HEADER_NAME)
    if not raw:
        return None
    return TenantId(raw)


def create_app(ledger: AuditLedgerPort) -> FastAPI:
    """Build the audit-ledger-service FastAPI app bound to `ledger`.

    `ledger` is injected by the caller (production wiring, or a fresh
    `InMemoryAuditLedger()` per test) — this factory holds no global mutable
    state of its own beyond what `ledger` already encapsulates.
    """
    app = FastAPI(title="saena-audit-ledger", version="0.1.0")

    # --- tenant header middleware (ADR-0014, tenant-safe logging) ------------------

    @app.middleware("http")
    async def _tenant_header_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            tenant_id = _parse_tenant_header(request)
        except InvalidTenantIdError as exc:
            return bad_request_problem(error_code=exc.error_code, detail=str(exc), request=request)
        request.state.tenant_id = tenant_id
        return await call_next(request)

    # --- POST /v1/audit/entries -----------------------------------------------------

    @app.post("/v1/audit/entries", status_code=201, response_model=EntryResponse)
    def append_entry(body: AppendEntryRequest, request: Request) -> EntryResponse | JSONResponse:
        if not has_permission(request, Permission.APPEND_AUDIT):
            return forbidden_rbac_problem(permission=Permission.APPEND_AUDIT.value, request=request)

        # error_code boundary guard (critic MUST-FIX 2, w2-10 review):
        # build_entry only runs guard_payload over `payload` and
        # guard_actor_fields over `actor` — it never inspects `error_code`,
        # so a caller-supplied error_code carrying guard-detectable content
        # (stack-trace fragments etc.) would otherwise be hashed into the
        # chain and echoed back forever on every future read. Run the same
        # guard over error_code BEFORE build_entry is called, wrapping it in
        # a dict (guard_payload's own signature, `saena_domain.audit.guard`)
        # so the existing key-path-only-in-message contract applies
        # identically to this field as to every `payload` key.
        if body.error_code is not None:
            try:
                guard_payload({"error_code": body.error_code})
            except ForbiddenAuditDataError as exc:
                return forbidden_audit_data_problem(exc, request=request)

        tenant_id = _resolve_scope_tenant(body.scope, body.tenant_id)
        actor = {"actor_id": body.actor_id} if body.actor_id is not None else None

        # The chain tail is owned by the ledger, not this handler — build_entry
        # needs prev_hash, and reading the full chain's last entry is the
        # only way AuditLedgerPort exposes the current tail for a scope.
        existing = ledger.read_range(tenant_id=tenant_id)
        tail_hash = existing[-1].event_hash.root if existing else None

        try:
            entry = build_entry(
                prev_hash=tail_hash,
                action=body.action,
                recorded_at=body.recorded_at,
                scope=body.scope,
                trace_id=body.trace_id,
                payload=body.payload,
                tenant_id=body.tenant_id,
                run_id=body.run_id,
                actor=actor,
                error_code=body.error_code,
            )
        except ForbiddenAuditDataError as exc:
            return forbidden_audit_data_problem(exc, request=request)
        except ValidationError as exc:
            # AuditEntry's own field-pattern re-validation inside build_entry
            # (e.g. action/trace_id/recorded_at/error_code pattern mismatch)
            # — routed through the same value-safe path as a top-level
            # RequestValidationError (critic MUST-FIX 1): never str(exc),
            # which embeds input_value=<raw value> verbatim.
            return validation_error_problem(exc, request=request)

        try:
            appended = ledger.append(entry)
        except ForbiddenAuditDataError as exc:
            return forbidden_audit_data_problem(exc, request=request)
        except ValueError as exc:
            return bad_request_problem(
                error_code="saena.audit_ledger.chain_link_rejected",
                detail=str(exc),
                request=request,
            )

        _logger.info(
            "%s appended",
            _APPENDED_LOG_ACTION,
            extra={
                "saena_attributes": {
                    "saena.audit_ledger.action": appended.action,
                    "saena.audit_ledger.scope": appended.scope.value,
                }
            },
        )
        return EntryResponse.from_entry(appended)

    # --- GET /v1/audit/entries --------------------------------------------------------

    @app.get("/v1/audit/entries", response_model=EntryListResponse)
    def read_entries(
        request: Request,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> EntryListResponse | JSONResponse:
        if not has_permission(request, Permission.READ_AUDIT):
            return forbidden_rbac_problem(permission=Permission.READ_AUDIT.value, request=request)

        tenant_id = getattr(request.state, "tenant_id", None)
        entries = ledger.read_range(
            tenant_id=tenant_id, start_index=start_index, end_index=end_index
        )
        return EntryListResponse(entries=[EntryResponse.from_entry(e) for e in entries])

    # --- GET /v1/audit/verify ----------------------------------------------------------

    @app.get("/v1/audit/verify", response_model=VerifyResponse)
    def verify(request: Request) -> VerifyResponse | JSONResponse:
        if not has_permission(request, Permission.READ_AUDIT):
            return forbidden_rbac_problem(permission=Permission.READ_AUDIT.value, request=request)

        tenant_id = getattr(request.state, "tenant_id", None)
        ok, first_broken_index = ledger.verify(tenant_id=tenant_id)
        return VerifyResponse(ok=ok, first_broken_index=first_broken_index)

    # --- GET /v1/audit/lineage/{lineage_ref} -------------------------------------------

    @app.get("/v1/audit/lineage/{lineage_ref}", response_model=EntryResponse)
    def resolve_lineage(lineage_ref: str, request: Request) -> EntryResponse | JSONResponse:
        # ADR-0013: view_lineage is granted to Role.AUDITOR ONLY — every
        # other role (including operator/service) is rejected with 403,
        # never merely "no entries returned".
        if not has_permission(request, Permission.VIEW_LINEAGE):
            return forbidden_rbac_problem(permission=Permission.VIEW_LINEAGE.value, request=request)

        if not is_lineage_ref(lineage_ref):
            return bad_request_problem(
                error_code="saena.audit_ledger.invalid_lineage_ref",
                detail="lineage_ref is not a well-formed 'audit:sha256:<64-hex>' reference",
                request=request,
            )

        # `AuditLedgerPort.read_range` only ever exposes ONE chain per call
        # (the caller's own tenant chain, or the system chain — never "every
        # tenant" in one call, by tenant-isolation design, `ports.py`
        # `AuditLedgerPort` docstring). A lineage ref carries no embedded
        # scope/tenant discriminator of its own (see `lineage.py` module
        # docstring — deliberately opaque), so resolving it searches exactly
        # the chain the caller's own request identifies: that tenant's chain
        # when `X-Saena-Tenant-Id` is supplied, the system chain otherwise.
        # An auditor resolving a tenant-scoped entry's ref MUST supply that
        # tenant's header — this endpoint does not (and, per tenant
        # isolation, must not) search every tenant's chain looking for a
        # match.
        tenant_id = getattr(request.state, "tenant_id", None)
        for entry in ledger.read_range(tenant_id=tenant_id):
            if make_lineage_ref(entry.event_hash.root) == lineage_ref:
                return EntryResponse.from_entry(entry)

        return not_found_problem(
            error_code="saena.audit_ledger.lineage_ref_not_found",
            detail=(
                "no ledger entry resolves to this lineage_ref within the "
                "requested scope (supply X-Saena-Tenant-Id to search a "
                "tenant-scoped chain, or omit it to search the system chain)"
            ),
            request=request,
        )

    # --- append-only enforcement: explicit 405 for mutation attempts ------------------
    #
    # Two distinct route registrations (PUT, DELETE) rather than one function
    # stacked under two decorators — FastAPI's `@app.<method>` decorators
    # each return the (undecorated) handler unchanged, so stacking them WOULD
    # work mechanically, but registering two independently-named routes here
    # keeps the route table's method/path entries explicit and individually
    # inspectable by `test_no_update_delete_routes_exist`.

    def _entries_immutable() -> JSONResponse:
        # `problem_response` (not `bad_request_problem`, which is fixed at
        # 400) so this handler's response actually carries 405 — FastAPI's
        # route-level `status_code=` is only an OpenAPI-doc default/fallback
        # for handlers that return a plain value; a handler that returns a
        # `Response` object directly (as every handler in this module does)
        # has ITS status code win, so it must be set here explicitly.
        return problem_response(
            status=405,
            title="Method not allowed",
            error_code="saena.audit_ledger.append_only",
            detail="the audit ledger is append-only; update/delete is not supported",
        )

    app.add_api_route("/v1/audit/entries", _entries_immutable, methods=["PUT"], status_code=405)
    app.add_api_route("/v1/audit/entries", _entries_immutable, methods=["DELETE"], status_code=405)

    @app.exception_handler(IdentityError)
    async def _identity_error_handler(request: Request, exc: IdentityError) -> JSONResponse:
        return domain_error_problem(exc, status=400, request=request)

    @app.exception_handler(PersistenceError)
    async def _persistence_error_handler(request: Request, exc: PersistenceError) -> JSONResponse:
        return domain_error_problem(exc, status=409, request=request)

    # --- value-echo hardening: replace FastAPI's default handlers (critic MUST-FIX 1) --
    #
    # FastAPI installs a DEFAULT `RequestValidationError` handler
    # (`fastapi.exception_handlers.request_validation_exception_handler`)
    # that returns `application/json` (not this service's problem+json
    # convention) with each error dict's raw `input` field intact — a
    # wrong-type request body's value is echoed straight back. Overriding it
    # here replaces that default for every route in this app. There is no
    # narrower "only override the leaky field" option: FastAPI does not
    # expose a hook to edit the default handler's output, only to replace it
    # wholesale — replacing it with `validation_error_problem` (value-safe by
    # construction, see `problem.py`) is the only way to close this channel.
    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return validation_error_problem(exc, request=request)

    # Catch-all: anything NOT already handled by a more specific handler
    # above (IdentityError/PersistenceError/RequestValidationError) — an
    # unexpected/unhandled exception must still never leak a stack trace or
    # exception message to the caller. Starlette dispatches to the handler
    # registered for the most specific matching type in the exception's MRO,
    # so this broad `Exception` handler only ever fires for genuinely
    # unanticipated errors, never shadowing the handlers above.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return internal_error_problem(request=request)

    return app


def _resolve_scope_tenant(scope: str, tenant_id: str | None) -> TenantId | None:
    """`AuditLedgerPort` scope-selection tenant_id: `None` for system scope,
    a validated `TenantId` for tenant scope.

    Mirrors `AuditEntry`'s own R9-1 scope rule (`chain.py`
    `_check_scope_rules`) at the port-selection boundary — `build_entry`
    will independently reject a scope/tenant_id mismatch when constructing
    the entry itself, so this only needs to pick which chain to read the
    tail from, not re-validate the full rule.
    """
    if scope == "system":
        return None
    if tenant_id is None:
        return None
    return TenantId(tenant_id)
