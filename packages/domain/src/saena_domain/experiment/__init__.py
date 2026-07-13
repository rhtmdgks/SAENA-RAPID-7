"""saena_domain.experiment — append-only experiment REGISTRATION ledger (w4-09).

Registration only. This package has no field, function, or method anywhere
that computes, stores, or exposes an experiment OUTCOME — no observed
metric value, effect size, lift, delta, DiD/causal estimate, or
significance judgement. That is Wave 5 (experiment-attribution-service's
outcome projection, per docs/decisions/ADR-0007-final-synthesis-ownership-
topology.md D-3: "TAG projection | 행동→실제 결과 연결 종점, 학습 루프 입력.
read-only CQRS"). `tests/unit/domain_experiment/test_no_outcome_fields.py`
pins this as an executable assertion.

Reuses `saena_domain.audit.canonical.canonical_json`/`sha256_hex` for
hashing rather than inventing a second canonicalization rule — see
`ledger.py`'s module docstring for the exact reuse, the content-fingerprint
vs. chain-entry-hash split (r4-03), and the shape it shares with
`saena_domain.audit.hashing.compute_entry_hash`.
"""

from __future__ import annotations

from saena_domain.experiment.errors import (
    ConflictError,
    ExperimentDomainError,
    RejectedError,
)
from saena_domain.experiment.ledger import (
    GENESIS,
    LedgerState,
    compute_content_fingerprint,
    compute_experiment_hash,
    register,
    verify_ledger,
)
from saena_domain.experiment.models import (
    FORBIDDEN_OUTCOME_TOKENS,
    ArmRole,
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)

__all__ = [
    "FORBIDDEN_OUTCOME_TOKENS",
    "GENESIS",
    "ArmRole",
    "ConflictError",
    "ExperimentArm",
    "ExperimentDomainError",
    "ExperimentRegistration",
    "LedgerState",
    "MetricDefinition",
    "RejectedError",
    "compute_content_fingerprint",
    "compute_experiment_hash",
    "register",
    "verify_ledger",
]
