"""Shared builders for the w5-03 deployment-confirmation + clock tests.

Everything here is deterministic and UTC-aware. Timestamps are anchored around
a fixed registration approval instant so backdate/future/Day-2 boundaries are
exact and reproducible. Nothing reads a wall clock — time is always explicit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from saena_domain.measurement.confirmation import (
    DeploymentConfirmation,
    RegistrationView,
    TrustVerifier,
)

#: Fixed registration timeline. created_at ≤ approved_at; both UTC-aware.
REG_CREATED_AT = datetime(2026, 7, 13, 9, 0, 0, tzinfo=UTC)
REG_APPROVED_AT = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)

#: A "server received" instant one day after approval — comfortably inside the
#: Day-2 window and after approval, so the default confirmation is Accepted.
SERVER_RECEIVED_AT = REG_APPROVED_AT + timedelta(days=1)

REGISTRATION_HASH = "sha256:" + "e" * 64


def registration_view(**overrides: Any) -> RegistrationView:
    base: dict[str, Any] = {
        "experiment_id": "exp-2026-0713-0001",
        "tenant_id": "acme-co",
        "run_id": "run-2026-0713-0001",
        "project": "acme-web",
        "site": "www.acme.example",
        "registration_canonical_hash": REGISTRATION_HASH,
        "created_at": REG_CREATED_AT,
        "approved_at": REG_APPROVED_AT,
    }
    base.update(overrides)
    return RegistrationView(**base)


def confirmation(**overrides: Any) -> DeploymentConfirmation:
    base: dict[str, Any] = {
        "experiment_id": "exp-2026-0713-0001",
        "tenant_id": "acme-co",
        "run_id": "run-2026-0713-0001",
        "project": "acme-web",
        "site": "www.acme.example",
        "registration_canonical_hash": REGISTRATION_HASH,
        "deployment_target": "prod/acme-web/edge",
        "deployed_commit_sha": "a" * 40,
        "artifact_hash": None,
        "confirmed_at": SERVER_RECEIVED_AT,
        "idempotency_key": "idem-0001",
        "confirmer_identity": "b-dept-deploy-bot",
        "confirmer_signature": "sig-" + "0" * 60,
    }
    base.update(overrides)
    return DeploymentConfirmation(**base)


class AcceptingVerifier:
    """A ``TrustVerifier`` that always trusts. Used for the happy path."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return True


class RejectingVerifier:
    """A ``TrustVerifier`` that never trusts. Used to prove fail-closed reject."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return False


def accepting_verifier() -> TrustVerifier:
    return AcceptingVerifier()


def rejecting_verifier() -> TrustVerifier:
    return RejectingVerifier()
