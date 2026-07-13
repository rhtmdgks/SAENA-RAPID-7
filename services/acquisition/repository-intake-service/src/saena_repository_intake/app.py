"""FastAPI app factory for `repository-intake-service` (W3, `JobKind.
REPOSITORY_INTAKE`).

Spec basis: `services/acquisition/repository-intake-service/README.md`
("Git/zip intake, commit pinning, SBOM·secret scan" / "Security boundary:
tenant-scoped secrets; secret scan before agent context"),
`docs/architecture/execution-runtime.md` (this `JobKind`'s pool/SA/read-only
facts), `packages/contracts/json-schema/domain/source-snapshot/v1/
source-snapshot.schema.json`, ADR-0014 (tenant propagation), ADR-0015 (RFC
9457 error format), ADR-0024(f) (uri fields reject `?`/`#`).

One route:

- `POST /v1/intake` — runs `core.perform_intake`'s full Input Gate against
  the request body's snapshot-reference fields, under the `JobContext`
  carried in the request body's own `job_context` object. No established
  HTTP header convention exists yet for `JobContext`'s non-`tenant_id`
  fields (unlike `X-Saena-Tenant-Id`, ADR-0014) — `JobContext` is a brand
  new W3 execution-domain concept this patch unit is the FIRST service to
  wire over HTTP at all, so this route accepts it as an explicit request
  body object rather than inventing an unreviewed header convention; a
  later unit standardizing `JobContext` HTTP propagation across all 5 W3
  job-kind services should revisit this, not silently diverge from it.
  `X-Saena-Tenant-Id` (ADR-0014) is still reconciled against
  `job_context.tenant_id` at the top of the handler, exactly like every
  other service in this repo.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from saena_domain.execution import JobContext
from saena_domain.identity import TenantId as DomainTenantId
from saena_domain.identity.errors import InvalidTenantIdError
from saena_domain.identity.http import TENANT_HEADER_NAME
from saena_observability.logging import get_logger

from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import RepositoryIntakeError
from saena_repository_intake.problem import (
    repository_intake_error_handler,
    request_validation_error_handler,
    unhandled_exception_handler,
)
from saena_repository_intake.protocols import (
    AuditSink,
    ContentHashVerifier,
    IntakeManifestStore,
    SecretScanner,
    WorkspaceStaging,
)

_logger = get_logger("saena_repository_intake")


class JobContextFields(BaseModel):
    """Every `JobContext` field (`saena_domain.execution`) — mandatory
    execution identity, carried explicitly on the request body (see module
    docstring "no established header convention yet")."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    workspace_id: str
    project_id: str
    run_id: str
    trace_id: str
    idempotency_key: str
    actor_id: str


class SnapshotIntakeRequest(BaseModel):
    """`POST /v1/intake` request body — a `SourceSnapshot`-shaped reference
    (never inline content; `model_config.extra="forbid"` alone already
    rejects an unrecognized field like `content_base64` with a 422 before
    `core.perform_intake` ever runs, and that function's own
    `InlineContentForbiddenError` check is a second, domain-level backstop
    for the same rule)."""

    model_config = ConfigDict(extra="forbid")

    job_context: JobContextFields
    tenant_id: str
    run_id: str
    repo_commit: str
    content_hash: str
    snapshot_uri: str
    source_type: str
    sbom_uri: str
    captured_at: str


class IntakeResponse(BaseModel):
    """`POST /v1/intake` response — the stored manifest plus the
    `repo.intaken.v1` event payload (on acceptance/replay only)."""

    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    event: dict[str, Any]
    replayed: bool


def _resolve_tenant_id(request: Request) -> str:
    header_value = request.headers.get(TENANT_HEADER_NAME)
    if not header_value:
        raise InvalidTenantIdError(
            f"{TENANT_HEADER_NAME} header is required",
            context={"header_name": TENANT_HEADER_NAME},
        )
    DomainTenantId(header_value)
    return header_value


def create_app(
    *,
    manifest_store: IntakeManifestStore,
    hash_verifier: ContentHashVerifier,
    secret_scanner: SecretScanner,
    audit_sink: AuditSink,
    workspace: WorkspaceStaging,
) -> FastAPI:
    """Build the `repository-intake-service` FastAPI app.

    Every port is injected — this factory wires no concrete adapter itself
    (callers pass `saena_repository_intake.memory`'s in-memory adapters for
    tests; a real deployment bootstrap supplies real
    `SecretScanner`/`ContentHashVerifier` adapters, out of this patch unit's
    scope, see `protocols.py`'s module docstring).
    """
    app = FastAPI(title="repository-intake-service")

    @app.middleware("http")
    async def _tenant_context_middleware(request: Request, call_next: Any) -> Response:
        try:
            tenant_id = _resolve_tenant_id(request)
        except InvalidTenantIdError as exc:
            mapped = RepositoryIntakeError(str(exc), context=exc.context)
            mapped.error_code = "saena.validation.tenant_id_invalid"
            mapped.status_code = 400
            return await repository_intake_error_handler(request, mapped)
        request.state.tenant_id = tenant_id
        return await call_next(request)

    app.add_exception_handler(RepositoryIntakeError, repository_intake_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.post("/v1/intake", status_code=201)
    async def intake(request: Request, body: SnapshotIntakeRequest) -> Response:
        header_tenant_id: str = request.state.tenant_id
        if body.job_context.tenant_id != header_tenant_id:
            error = RepositoryIntakeError(
                f"{TENANT_HEADER_NAME} header does not match job_context.tenant_id",
                context={
                    "header_tenant_id": header_tenant_id,
                    "job_context_tenant_id": body.job_context.tenant_id,
                },
            )
            error.error_code = "saena.validation.tenant_id_mismatch"
            error.status_code = 400
            raise error

        job_context = JobContext(**body.job_context.model_dump())
        payload = body.model_dump(exclude={"job_context"})

        outcome = perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

        _logger.info(
            "repository intake accepted",
            extra={
                "saena_attributes": {
                    "saena.tenant_id": header_tenant_id,
                    "repository_intake.content_hash": outcome.manifest.content_hash,
                    "repository_intake.replayed": outcome.replayed,
                }
            },
        )

        status_code = 200 if outcome.replayed else 201
        return Response(
            content=IntakeResponse(
                manifest=outcome.manifest.to_dict(),
                event=outcome.event_payload,
                replayed=outcome.replayed,
            ).model_dump_json(),
            status_code=status_code,
            media_type="application/json",
        )

    return app


__all__ = [
    "IntakeResponse",
    "JobContextFields",
    "SnapshotIntakeRequest",
    "create_app",
]
