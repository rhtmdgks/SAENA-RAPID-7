"""Tenant-safe logging — customer-proprietary MAX sensitivity (PatchArtifact
row, contract-catalog.md "diff=소스"): logs must carry hashes/sizes only,
NEVER blob content or raw manifest bytes."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from registry_factories import build_register_request


def test_register_and_fetch_logs_contain_no_blob_content(
    client: TestClient, tenant_headers: dict[str, str], caplog: object
) -> None:
    secret_blob = b"THIS-IS-SECRET-CUSTOMER-SOURCE-DIFF-CONTENT-xyz123"
    logger = logging.getLogger("saena_artifact_registry")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        register_response = client.post(
            "/v1/artifacts",
            json=build_register_request(blob=secret_blob),
            headers=tenant_headers,
        )
        assert register_response.status_code == 201

        fetch_response = client.get(
            "/v1/artifacts/w2-16-artifact-registry/9f1c2e7/blob", headers=tenant_headers
        )
        assert fetch_response.status_code == 200
    finally:
        logger.removeHandler(handler)

    assert records, "expected at least one log record to be emitted"
    for record in records:
        message = record.getMessage()
        assert secret_blob.decode() not in message
        for value in getattr(record, "saena_attributes", {}).values():
            assert secret_blob.decode() not in str(value)


def test_log_records_carry_only_hash_and_size_not_content(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    logger = logging.getLogger("saena_artifact_registry")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)
    finally:
        logger.removeHandler(handler)

    registered_records = [r for r in records if "registered" in r.getMessage()]
    assert registered_records, "expected an 'artifact manifest registered' log record"
    attrs = registered_records[0].saena_attributes  # type: ignore[attr-defined]
    assert "artifact_registry.blob_sha256" in attrs
    assert "artifact_registry.blob_size_bytes" in attrs
    assert not any("content" in key.lower() for key in attrs)
