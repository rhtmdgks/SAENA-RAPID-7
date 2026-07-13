"""NEGATIVE TEST: unsupported source type (mission item 4, closed set
`{"git", "zip"}`)."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import UnsupportedSourceTypeError


def test_unsupported_source_type_is_refused(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload(source_type="svn")

    with pytest.raises(UnsupportedSourceTypeError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    assert excinfo.value.error_code == "saena.validation.unsupported_source_type"
    assert excinfo.value.context["allowed"] == ["git", "zip"]
    assert workspace.outstanding == frozenset()
