"""Factory helpers shared by ``tests/unit/svc_experiment_attribution_workflow``
and ``tests/integration/measurement_workflow`` (mirrors
``tests/unit/svc_orchestrator/orchestrator_factories.py``).

Constructs ``Accepted``/``RegistrationView`` fixtures for the measurement
workflow tests. These build an ``Accepted`` DIRECTLY (bypassing
``validate_confirmation``) — these suites exercise the WORKFLOW's structural
re-check over an already-Accepted payload; upstream validation is w5-03's tested
concern, not re-tested here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saena_domain.measurement.confirmation import (
    Accepted,
    DeploymentConfirmation,
    RegistrationView,
)

REGISTRATION_HASH = "sha256:" + "a" * 64
OTHER_REGISTRATION_HASH = "sha256:" + "b" * 64
TENANT = "tenant-eaas-1"
RUN_ID = "run-eaas-0001"
EXPERIMENT_ID = "exp-eaas-0001"
IDEMPOTENCY_KEY = "idem-eaas-0001"

#: A fixed absolute base instant used as both created_at/approved_at and the
#: default server_received_at anchor (Day 0, on-time deployment).
BASE_INSTANT = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)


def make_registration_view(*, approved_at: datetime | None = None) -> RegistrationView:
    return RegistrationView(
        experiment_id=EXPERIMENT_ID,
        tenant_id=TENANT,
        run_id=RUN_ID,
        project="proj-eaas",
        site="site-eaas",
        registration_canonical_hash=REGISTRATION_HASH,
        created_at=BASE_INSTANT,
        approved_at=approved_at or BASE_INSTANT,
    )


def make_confirmation(
    *,
    idempotency_key: str = IDEMPOTENCY_KEY,
    deployed_commit_sha: str = "commit-abc123",
) -> DeploymentConfirmation:
    return DeploymentConfirmation(
        experiment_id=EXPERIMENT_ID,
        tenant_id=TENANT,
        run_id=RUN_ID,
        project="proj-eaas",
        site="site-eaas",
        registration_canonical_hash=REGISTRATION_HASH,
        deployment_target="prod-eaas",
        deployed_commit_sha=deployed_commit_sha,
        confirmed_at=BASE_INSTANT + timedelta(hours=12),
        idempotency_key=idempotency_key,
        confirmer_identity="confirmer-eaas",
        confirmer_signature="sig-eaas",
    )


def make_accepted(
    *,
    idempotency_key: str = IDEMPOTENCY_KEY,
    deployed_commit_sha: str = "commit-abc123",
    server_received_at: datetime | None = None,
    approved_at: datetime | None = None,
    registration_hash: str = REGISTRATION_HASH,
    content_fingerprint: str | None = None,
) -> Accepted:
    """Build an ``Accepted``. ``registration_hash`` lets a test build one whose
    embedded registration deliberately mismatches the run's expected hash (the
    structural-refusal path). ``content_fingerprint`` defaults to a deterministic
    value distinct per (key, commit) so duplicate vs. conflicting classification
    is exercised without depending on the real audit-canonical hash (that reuse
    is validated in w5-03's own tests).
    """
    reg = make_registration_view(approved_at=approved_at)
    confirmation = make_confirmation(
        idempotency_key=idempotency_key,
        deployed_commit_sha=deployed_commit_sha,
    )
    if registration_hash != REGISTRATION_HASH:
        reg = reg.model_copy(update={"registration_canonical_hash": registration_hash})
        confirmation = confirmation.model_copy(
            update={"registration_canonical_hash": registration_hash}
        )
    anchor = server_received_at or (BASE_INSTANT + timedelta(hours=12))
    fp = content_fingerprint or f"fp:{idempotency_key}:{deployed_commit_sha}"
    return Accepted(
        confirmation=confirmation,
        registration_view=reg,
        server_received_at=anchor,
        content_fingerprint=fp,
    )
