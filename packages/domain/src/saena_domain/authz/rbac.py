"""RBAC role/permission enums, explicit allow matrix, default-deny authorize().

Task instruction 6 (spec basis for this module):
    Role enum (minimum: operator, proposer, approver, auditor,
    contracts_steward, service) + Permission enum (propose_plan, approve_plan,
    execute_plan, view_lineage, append_audit, read_audit, manage_tenant,
    publish_aggregate) + explicit allow matrix; authorize(roles, permission)
    default-DENY; view_lineage granted ONLY to auditor (ADR-0013
    lineage_audit_ref audit-role-only).

Matrix design rationale (this module's own interpretation — no schema/ADR
enumerates a full RBAC matrix, only the view_lineage=auditor-only constraint
is explicitly sourced; the rest follows role names by their evident
least-privilege meaning, flagged as an OPEN ITEM):

    - proposer:            propose_plan
    - approver:             approve_plan
    - operator:             execute_plan (runs approved plans; k3s §5.2
                             'runner' pool is operational infrastructure, not
                             an approval role)
    - auditor:               view_lineage, read_audit (ADR-0013 audit-role-only
                             lineage; read access to the audit trail is the
                             defining capability of this role)
    - contracts_steward:     manage_tenant, publish_aggregate (single-owner
                             contract/schema/tenant-config custodian per
                             CLAUDE.md operating principle 7 '단일 owner' —
                             closest existing role to that custodian function)
    - service:               append_audit (machine-to-machine audit writers —
                             services append audit records; only auditor
                             reads them back, enforcing write-only for
                             machine callers)

    No role is granted ALL permissions; no role is granted view_lineage other
    than auditor (the one explicitly mandated constraint). Every permission
    is granted to at least one role; every role has at least one permission.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    PROPOSER = "proposer"
    APPROVER = "approver"
    AUDITOR = "auditor"
    CONTRACTS_STEWARD = "contracts_steward"
    SERVICE = "service"


class Permission(StrEnum):
    PROPOSE_PLAN = "propose_plan"
    APPROVE_PLAN = "approve_plan"
    EXECUTE_PLAN = "execute_plan"
    VIEW_LINEAGE = "view_lineage"
    APPEND_AUDIT = "append_audit"
    READ_AUDIT = "read_audit"
    MANAGE_TENANT = "manage_tenant"
    PUBLISH_AGGREGATE = "publish_aggregate"


# Explicit allow matrix: Role -> frozenset[Permission]. Absence of a role, or
# absence of a permission from a role's set, means DENY (default-deny is
# enforced structurally by authorize() never falling through to an implicit
# allow — see authorize() below).
ALLOW_MATRIX: dict[Role, frozenset[Permission]] = {
    Role.PROPOSER: frozenset({Permission.PROPOSE_PLAN}),
    Role.APPROVER: frozenset({Permission.APPROVE_PLAN}),
    Role.OPERATOR: frozenset({Permission.EXECUTE_PLAN}),
    Role.AUDITOR: frozenset({Permission.VIEW_LINEAGE, Permission.READ_AUDIT}),
    Role.CONTRACTS_STEWARD: frozenset({Permission.MANAGE_TENANT, Permission.PUBLISH_AGGREGATE}),
    Role.SERVICE: frozenset({Permission.APPEND_AUDIT}),
}


def authorize(
    roles: frozenset[Role] | set[Role] | tuple[Role, ...], permission: Permission
) -> bool:
    """Default-deny authorization check.

    Returns True iff at least one role in `roles` is present in ALLOW_MATRIX
    AND that role's allowed-permission set contains `permission`. Any
    unrecognized role, empty role set, or permission absent from every held
    role's set returns False — there is no implicit-allow path.

    view_lineage is granted ONLY to Role.AUDITOR by construction of
    ALLOW_MATRIX above (ADR-0013) — this function does not special-case it;
    the matrix itself is the single source of truth, which also makes the
    "auditor-only" property directly testable by inspecting ALLOW_MATRIX.
    """
    for role in roles:
        allowed = ALLOW_MATRIX.get(role)
        if allowed is not None and permission in allowed:
            return True
    return False
