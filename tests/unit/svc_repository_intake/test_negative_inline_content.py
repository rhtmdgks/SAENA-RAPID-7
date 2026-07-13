"""Mission item 5: inline source content FORBIDDEN — only immutable
snapshot references accepted."""

from __future__ import annotations

import pytest
from intake_factories import build_snapshot_payload
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import InlineContentForbiddenError


def test_inline_content_field_is_rejected_before_anything_else(
    job_context, manifest_store, hash_verifier, secret_scanner, audit_sink, workspace
):
    payload = build_snapshot_payload()
    payload["content_base64"] = "ZmFrZSBzb3VyY2UgYnl0ZXM="  # never reached, structural reject

    with pytest.raises(InlineContentForbiddenError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    assert excinfo.value.context["forbidden_fields"] == ["content_base64"]
    # never consulted the hash verifier / secret scanner at all — rejected
    # purely on the forbidden field's presence, before any network-shaped
    # port is ever called
    assert workspace.outstanding == frozenset()
