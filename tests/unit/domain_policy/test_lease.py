"""Per-patch-unit lease value object (H-7)."""

from __future__ import annotations

import pytest
from saena_domain.policy.lease import PatchUnitLease, issue_lease


def test_issue_lease_builds_value_object() -> None:
    lease = issue_lease(
        patch_unit_id="PU-01",
        scope=("apps/web/docs/*",),
        expiry="2026-07-12T12:00:00Z",
    )
    assert isinstance(lease, PatchUnitLease)
    assert lease.patch_unit_id == "PU-01"
    assert lease.scope == ("apps/web/docs/*",)
    assert lease.expiry == "2026-07-12T12:00:00Z"


def test_lease_is_frozen_value_object() -> None:
    lease = issue_lease(patch_unit_id="PU-01", scope=(), expiry="2026-07-12T12:00:00Z")
    with pytest.raises(AttributeError):
        lease.patch_unit_id = "PU-02"  # type: ignore[misc]


def test_issue_lease_rejects_empty_patch_unit_id() -> None:
    with pytest.raises(ValueError, match="patch_unit_id"):
        issue_lease(patch_unit_id="", scope=(), expiry="2026-07-12T12:00:00Z")
