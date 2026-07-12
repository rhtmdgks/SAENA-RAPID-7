"""RBAC default-deny + per-role grants + view_lineage restriction (ADR-0013)."""

from __future__ import annotations

import pytest
from saena_domain.authz.rbac import ALLOW_MATRIX, Permission, Role, authorize


def test_default_deny_empty_roles() -> None:
    assert not authorize(set(), Permission.PROPOSE_PLAN)


def test_default_deny_unrecognized_role_like_object_not_in_matrix() -> None:
    # A role that legitimately exists in the enum but has no matrix entry
    # would also deny; here we assert every Role IS present (no silent
    # fallthrough) and that permissions not in a role's set are denied.
    assert not authorize({Role.OPERATOR}, Permission.MANAGE_TENANT)


@pytest.mark.parametrize(
    "role,permission",
    [
        (Role.PROPOSER, Permission.PROPOSE_PLAN),
        (Role.APPROVER, Permission.APPROVE_PLAN),
        (Role.OPERATOR, Permission.EXECUTE_PLAN),
        (Role.AUDITOR, Permission.VIEW_LINEAGE),
        (Role.AUDITOR, Permission.READ_AUDIT),
        (Role.CONTRACTS_STEWARD, Permission.MANAGE_TENANT),
        (Role.CONTRACTS_STEWARD, Permission.PUBLISH_AGGREGATE),
        (Role.SERVICE, Permission.APPEND_AUDIT),
    ],
)
def test_per_role_grants(role: Role, permission: Permission) -> None:
    assert authorize({role}, permission)


@pytest.mark.parametrize(
    "role,permission",
    [
        (Role.PROPOSER, Permission.APPROVE_PLAN),
        (Role.PROPOSER, Permission.EXECUTE_PLAN),
        (Role.PROPOSER, Permission.VIEW_LINEAGE),
        (Role.APPROVER, Permission.PROPOSE_PLAN),
        (Role.APPROVER, Permission.VIEW_LINEAGE),
        (Role.OPERATOR, Permission.PROPOSE_PLAN),
        (Role.OPERATOR, Permission.APPROVE_PLAN),
        (Role.OPERATOR, Permission.VIEW_LINEAGE),
        (Role.CONTRACTS_STEWARD, Permission.VIEW_LINEAGE),
        (Role.CONTRACTS_STEWARD, Permission.EXECUTE_PLAN),
        (Role.SERVICE, Permission.VIEW_LINEAGE),
        (Role.SERVICE, Permission.READ_AUDIT),
        (Role.SERVICE, Permission.EXECUTE_PLAN),
    ],
)
def test_per_role_denies(role: Role, permission: Permission) -> None:
    assert not authorize({role}, permission)


def test_view_lineage_granted_only_to_auditor() -> None:
    for role in Role:
        result = authorize({role}, Permission.VIEW_LINEAGE)
        if role is Role.AUDITOR:
            assert result
        else:
            assert not result, f"{role} must NOT have view_lineage (ADR-0013)"


def test_view_lineage_in_allow_matrix_only_under_auditor() -> None:
    for role, permissions in ALLOW_MATRIX.items():
        if role is Role.AUDITOR:
            assert Permission.VIEW_LINEAGE in permissions
        else:
            assert Permission.VIEW_LINEAGE not in permissions


def test_multi_role_union_grants_if_any_role_grants() -> None:
    assert authorize({Role.OPERATOR, Role.AUDITOR}, Permission.VIEW_LINEAGE)
    assert authorize({Role.OPERATOR, Role.AUDITOR}, Permission.EXECUTE_PLAN)
    assert not authorize({Role.OPERATOR, Role.PROPOSER}, Permission.VIEW_LINEAGE)


def test_every_role_has_at_least_one_permission() -> None:
    for role in Role:
        assert ALLOW_MATRIX.get(role), f"{role} has no granted permissions"


def test_every_permission_granted_to_at_least_one_role() -> None:
    granted: set[Permission] = set()
    for permissions in ALLOW_MATRIX.values():
        granted |= permissions
    for permission in Permission:
        assert permission in granted, f"{permission} is unreachable by any role"


def test_no_role_holds_every_permission() -> None:
    all_permissions = set(Permission)
    for role, permissions in ALLOW_MATRIX.items():
        assert permissions != all_permissions, f"{role} must not hold all permissions"
