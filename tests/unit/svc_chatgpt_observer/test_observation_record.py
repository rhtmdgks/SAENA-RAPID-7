"""PlatformObservation record + observation.captured.v1 envelope (w4-08):
validated against the REAL w4-10 generated models; engine_id closed-enum guard;
the event payload never carries raw_object_ref / tenant_id."""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.platform_observation_record import (
    PlatformObservationRecordError,
    build_observation_captured_envelope,
    build_platform_observation_record,
)
from saena_domain.execution.errors import EngineNotPermittedError

from .conftest import ENGINE, RUN_ID, TENANT_A

_OBS_ID = f"{RUN_ID}-0000"
_REF = f"artifact://{TENANT_A}/{'a' * 64}"
_HASH = "sha256:" + "a" * 64


def _record(**over):
    kw = dict(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        engine_id=ENGINE,
        observation_id=_OBS_ID,
        raw_object_ref=_REF,
        artifact_hash=_HASH,
        citation_refs=("https://example.com/a",),
        captured_at="2026-07-13T00:00:00Z",
    )
    kw.update(over)
    return build_platform_observation_record(**kw)


def test_record_validates_against_real_generated_model() -> None:
    rec = _record()
    assert rec["tenant_id"] == TENANT_A
    assert rec["engine_id"] == ENGINE
    assert rec["raw_object_ref"] == _REF
    assert rec["artifact_hash"] == _HASH


def test_record_rejects_non_chatgpt_search_engine() -> None:
    for bad in ("google-aio", "gemini", "google-ai-mode", "bing"):
        with pytest.raises(EngineNotPermittedError):
            _record(engine_id=bad)


def test_record_rejects_malformed_artifact_hash() -> None:
    with pytest.raises(PlatformObservationRecordError):
        _record(artifact_hash="not-a-sha")


def test_captured_envelope_payload_is_minimal_and_leaks_nothing() -> None:
    env = build_observation_captured_envelope(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        engine_id=ENGINE,
        observation_id=_OBS_ID,
        artifact_hash=_HASH,
        idempotency_key=f"{TENANT_A}:{RUN_ID}:{_OBS_ID}",
    )
    payload = env["payload"]
    assert set(payload) == {"engine_id", "observation_id", "artifact_hash"}
    # raw-content-adjacent + envelope-duplicated fields never appear in payload
    assert "raw_object_ref" not in payload
    assert "tenant_id" not in payload
    assert payload["engine_id"] == ENGINE
    # tenant_id lives on the (flat) envelope, not the payload
    assert env["tenant_id"] == TENANT_A
    assert env["event_type"] == "observation.captured.v1"


def test_captured_envelope_rejects_disallowed_engine() -> None:
    with pytest.raises(EngineNotPermittedError):
        build_observation_captured_envelope(
            tenant_id=TENANT_A,
            run_id=RUN_ID,
            engine_id="gemini",
            observation_id=_OBS_ID,
            artifact_hash=_HASH,
            idempotency_key="k",
        )
