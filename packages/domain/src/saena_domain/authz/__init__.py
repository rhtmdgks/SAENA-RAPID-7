"""saena_domain.authz — RBAC role/permission model, default-deny authorize().

Authority: task instruction 6; ADR-0013 lineage_audit_ref ("audit role
전용 열람" — docs/decisions/ADR-0013-event-envelope-v1.md:66); contract-catalog.md
ApprovalDecision Sensitivity PII+internal.
"""

from __future__ import annotations

from saena_domain.authz.rbac import (
    ALLOW_MATRIX,
    Permission,
    Role,
    authorize,
)

__all__ = [
    "ALLOW_MATRIX",
    "Permission",
    "Role",
    "authorize",
]
