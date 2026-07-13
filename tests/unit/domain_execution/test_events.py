"""Event payload builders — output validated against the REAL contract JSON
Schema files (jsonschema, local registry — see _schema_support.py) in
addition to the pydantic model validation the builders perform internally."""

from __future__ import annotations

import pytest
from _schema_support import (
    PATCH_UNIT_COMPLETED_SCHEMA_PATH,
    QUALITY_GATE_RESULT_SCHEMA_PATH,
    REPO_INTAKEN_SCHEMA_PATH,
    SITE_INVENTORY_COMPLETED_SCHEMA_PATH,
    schema_errors,
)
from saena_domain.execution.errors import EventPayloadValidationError
from saena_domain.execution.events import (
    build_patch_unit_completed_payload,
    build_quality_gate_failed_payload,
    build_quality_gate_passed_payload,
    build_repo_intaken_payload,
    build_site_inventory_completed_payload,
)
from saena_domain.execution.job_error import JobError

_GIT_SHA = "a" * 40
_SHA256_REF = "sha256:" + "b" * 64


# --------------------------------------------------------------------------
# repo.intaken.v1
# --------------------------------------------------------------------------


def test_build_repo_intaken_payload_minimal() -> None:
    payload = build_repo_intaken_payload(repo_commit=_GIT_SHA, content_hash=_SHA256_REF)
    assert payload == {"repo_commit": _GIT_SHA, "content_hash": _SHA256_REF}
    assert schema_errors(REPO_INTAKEN_SCHEMA_PATH, payload) == []


def test_build_repo_intaken_payload_with_snapshot_uri() -> None:
    payload = build_repo_intaken_payload(
        repo_commit=_GIT_SHA,
        content_hash=_SHA256_REF,
        snapshot_uri="s3://bucket/snapshot",
    )
    assert payload["snapshot_uri"] == "s3://bucket/snapshot"
    assert schema_errors(REPO_INTAKEN_SCHEMA_PATH, payload) == []


def test_build_repo_intaken_payload_rejects_bad_repo_commit() -> None:
    with pytest.raises(EventPayloadValidationError):
        build_repo_intaken_payload(repo_commit="not-a-sha", content_hash=_SHA256_REF)


# --------------------------------------------------------------------------
# patch.unit.completed.v1
# --------------------------------------------------------------------------


def test_build_patch_unit_completed_payload_minimal() -> None:
    payload = build_patch_unit_completed_payload(
        patch_unit_id="w3-01-exec-arch", worktree_commit="9f1c2e7"
    )
    assert payload == {"patch_unit_id": "w3-01-exec-arch", "worktree_commit": "9f1c2e7"}
    assert schema_errors(PATCH_UNIT_COMPLETED_SCHEMA_PATH, payload) == []


def test_build_patch_unit_completed_payload_full() -> None:
    payload = build_patch_unit_completed_payload(
        patch_unit_id="w3-01-exec-arch",
        worktree_commit="9f1c2e7",
        manifest_uri="s3://bucket/manifest.json",
        changed_files=["a.py", "b.py"],
        quality_gate_ids=["lint", "unit"],
    )
    assert payload["changed_files"] == ["a.py", "b.py"]
    assert payload["quality_gate_ids"] == ["lint", "unit"]
    assert schema_errors(PATCH_UNIT_COMPLETED_SCHEMA_PATH, payload) == []


def test_build_patch_unit_completed_payload_rejects_empty_patch_unit_id() -> None:
    with pytest.raises(EventPayloadValidationError):
        build_patch_unit_completed_payload(patch_unit_id="", worktree_commit="9f1c2e7")


def test_build_patch_unit_completed_payload_rejects_bad_worktree_commit() -> None:
    with pytest.raises(EventPayloadValidationError):
        build_patch_unit_completed_payload(patch_unit_id="unit-1", worktree_commit="zzz")


# --------------------------------------------------------------------------
# quality.gate.passed.v1 / quality.gate.failed.v1
# --------------------------------------------------------------------------


def test_build_quality_gate_passed_payload_never_carries_failures_key() -> None:
    payload = build_quality_gate_passed_payload(patch_unit_id="unit-1", gate_id="lint")
    assert "failures" not in payload
    assert schema_errors(QUALITY_GATE_RESULT_SCHEMA_PATH, payload) == []


def test_build_quality_gate_passed_payload_with_report_uri() -> None:
    payload = build_quality_gate_passed_payload(
        patch_unit_id="unit-1", gate_id="lint", report_uri="s3://bucket/report.json"
    )
    assert payload["report_uri"] == "s3://bucket/report.json"
    assert schema_errors(QUALITY_GATE_RESULT_SCHEMA_PATH, payload) == []


def test_build_quality_gate_failed_payload_requires_at_least_one_failure() -> None:
    with pytest.raises(EventPayloadValidationError):
        build_quality_gate_failed_payload(patch_unit_id="unit-1", gate_id="lint", failures=[])


def test_build_quality_gate_failed_payload_with_failures() -> None:
    failures = [
        JobError(
            error_code="saena.validation.schema_mismatch",
            summary="lint rule E501 violated",
            retryable=False,
        )
    ]
    payload = build_quality_gate_failed_payload(
        patch_unit_id="unit-1", gate_id="lint", failures=failures
    )
    assert payload["failures"] == [
        {
            "error_code": "saena.validation.schema_mismatch",
            "retryable": False,
            "summary": "lint rule E501 violated",
        }
    ]
    assert schema_errors(QUALITY_GATE_RESULT_SCHEMA_PATH, payload) == []


# --------------------------------------------------------------------------
# site.inventory.completed.v1
# --------------------------------------------------------------------------


def test_build_site_inventory_completed_payload() -> None:
    payload = build_site_inventory_completed_payload(
        site_id="site-0001", inventory_version="2026-07-13T00:00:00Z"
    )
    assert payload == {"site_id": "site-0001", "inventory_version": "2026-07-13T00:00:00Z"}
    assert schema_errors(SITE_INVENTORY_COMPLETED_SCHEMA_PATH, payload) == []


def test_build_site_inventory_completed_payload_rejects_empty_site_id() -> None:
    with pytest.raises(EventPayloadValidationError):
        build_site_inventory_completed_payload(site_id="", inventory_version="v1")
