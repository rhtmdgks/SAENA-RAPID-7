"""Wave-4 intelligence: artifact single-gateway ref discipline (w4-16).

Mission hard constraint (`saena_chatgpt_observer.artifact_gateway` module
docstring, verbatim): "raw response HTML/screenshot is NEVER stored inline
in the observation. It is persisted through the artifact-registry single
gateway and the observation carries only a content-addressed
`raw_object_ref` + `artifact_hash`."

This module proves, end to end against the REAL `run_pooled_observation`
pipeline (w4-08) plus the record/event builders it calls
(`platform_observation_record.py`, w4-10), that raw captured bytes NEVER
appear anywhere except inside the single gateway
(`FakeArtifactGateway`'s own internal store) — not in the
`PlatformObservation` record, not in the `observation.captured.v1` event
envelope, not in the run's audit trail, and not in a (simulated)
structured-log line an observability sink would emit for any of those
three.

Every assertion below is adversarial by construction: it plants a UNIQUE,
easily-greppable raw-content marker (`_RAW_MARKER`) into the captured
bytes and then asserts that marker is byte-for-byte ABSENT from every
outward-facing structure. If the single-gateway boundary were bypassed
(e.g. a future change embedded `raw_content` directly into the record or
event "for debugging"), the marker would appear in at least one of these
serialized outputs and the corresponding assertion would fail.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
from saena_chatgpt_observer.pool_capture import run_pooled_observation
from saena_domain.execution import JobContext

TENANT_ID = "acme-co"
RUN_ID = "run-0001"

#: A unique marker byte string standing in for real captured raw HTML/
#: screenshot content — chosen to be trivially greppable in any serialized
#: (dict/JSON/audit-log) representation this test inspects, so "the marker
#: is absent" is a strong, specific proof rather than a vague shape check.
_RAW_MARKER = b"<!-- RAW-ARTIFACT-DO-NOT-LEAK-9f3c7a2e -->"
_RAW_HTML = b"<html><body>chatgpt search result page" + _RAW_MARKER + b"</body></html>"


def _make_job_context() -> JobContext:
    return JobContext(
        tenant_id=TENANT_ID,
        workspace_id="ws-0001",
        project_id="proj-0001",
        run_id=RUN_ID,
        trace_id="a" * 32,
        idempotency_key=f"{TENANT_ID}:{RUN_ID}:w4-16-artifact",
        actor_id="actor-0001",
    )


def _run_pooled_capture(query_text: str = "what is saena"):
    factory = FixtureBrowserSessionFactory(shared_responses={query_text: _RAW_HTML})
    pool = BrowserPool(factory, max_size=1)
    artifact_gateway = FakeArtifactGateway()
    result = run_pooled_observation(
        job_context=_make_job_context(),
        pool=pool,
        artifact_gateway=artifact_gateway,
        engine_id="chatgpt-search",
        queries=[query_text],
    )
    return result, artifact_gateway


def _simulate_log_line(obj: object) -> str:
    """Stand-in for a real observability sink's structured-log serializer —
    JSON-dumps whatever a real sink would receive. Not this suite's real
    logging pipeline (out of scope), but a faithful enough simulation that
    "the marker never reaches this string" is a meaningful proof: any real
    JSON/structlog/OTel-attribute sink serializes a Python dict the exact
    same way, so a leak into `obj` would leak into a real log line too.
    """
    return json.dumps(obj, default=str, sort_keys=True)


def test_platform_observation_record_never_contains_raw_content() -> None:
    """Pins `build_platform_observation_record`'s field discipline (task
    instruction: "exactly `{tenant_id, run_id, engine_id, observation_id,
    raw_object_ref, artifact_hash, citation_refs, captured_at}` — never the
    raw response HTML/screenshot inline"). Fails if a future change added
    the raw bytes (or a decoded/truncated form of them) to this record."""
    result, _gateway = _run_pooled_capture()
    record = result.results[0].observation_record

    assert _RAW_MARKER not in _simulate_log_line(record).encode()
    assert set(record.keys()) == {
        "tenant_id",
        "run_id",
        "engine_id",
        "observation_id",
        "raw_object_ref",
        "artifact_hash",
        "citation_refs",
        "captured_at",
    }
    # The ref itself must be opaque (content-addressed), never the raw bytes
    # or anything resolvable back to them without going through the gateway.
    assert record["raw_object_ref"].startswith(f"artifact://{TENANT_ID}/")
    assert record["artifact_hash"].startswith("sha256:")


def test_observation_captured_envelope_never_contains_raw_content_or_raw_object_ref() -> None:
    """Pins `build_observation_captured_envelope`'s field discipline (task
    instruction: payload carries `engine_id`/`observation_id`/
    `artifact_hash` ONLY — "NEVER `raw_object_ref`" per that function's own
    docstring, since even the opaque ref is considered raw-content-adjacent
    at the notification-event layer). Fails if `raw_object_ref` (or the raw
    bytes) leaked into the published event payload.
    """
    result, _gateway = _run_pooled_capture()
    envelope = result.results[0].observation_captured_envelope
    payload = envelope["payload"]

    serialized = _simulate_log_line(envelope)
    assert _RAW_MARKER not in serialized.encode()
    assert "raw_object_ref" not in payload
    assert set(payload.keys()) == {"engine_id", "observation_id", "artifact_hash"}


def test_audit_trail_never_contains_raw_content() -> None:
    """Pins `run_pooled_observation`'s own `AuditEntry` construction (module
    docstring: "this module never logs them [raw bytes], never returns them
    to a caller, never embeds them in the audit trail or the built
    record/event"). Fails if a future change logged `query_text` alongside
    the raw response for debugging."""
    result, _gateway = _run_pooled_capture()
    audit_trail = result.audit_trail

    serialized = _simulate_log_line([asdict(entry) for entry in audit_trail])
    assert _RAW_MARKER not in serialized.encode()


def test_pooled_observation_result_and_run_result_top_level_never_contain_raw_content() -> None:
    """Whole-result sweep: serializes EVERY field this pipeline call
    returns (not just the sub-objects the tests above already isolate) and
    asserts the marker is absent everywhere — a broader net catching any
    NEW field a future change might add that re-embeds raw content without
    this suite having been updated to name it explicitly."""
    result, _gateway = _run_pooled_capture()

    whole_result_dump = _simulate_log_line(
        {
            "results": [
                {
                    "observation_record": r.observation_record,
                    "observation_captured_envelope": r.observation_captured_envelope,
                    "raw_object_ref": r.raw_object_ref,
                    "artifact_hash": r.artifact_hash,
                }
                for r in result.results
            ],
            "audit_trail": [asdict(entry) for entry in result.audit_trail],
            "final_status": str(result.final_status),
        }
    )
    assert _RAW_MARKER not in whole_result_dump.encode()


def test_only_the_gateways_own_sanctioned_read_path_ever_recovers_the_raw_marker() -> None:
    """Positive control proving this is a REAL, meaningful test (not a
    tautology that would pass even if capture silently dropped the raw
    content instead of routing it through the gateway): the marker MUST be
    recoverable from `FakeArtifactGateway.get_raw_artifact` — the ONE
    sanctioned read path — using only the public `raw_object_ref`/
    `artifact_hash` fields a real downstream caller would actually have
    (never reaching into the gateway's private internal store).
    """
    from saena_chatgpt_observer.artifact_gateway import RawArtifactRef

    result, gateway = _run_pooled_capture()
    pooled_result = result.results[0]
    ref = RawArtifactRef(
        raw_object_ref=pooled_result.raw_object_ref, artifact_hash=pooled_result.artifact_hash
    )

    recovered = gateway.get_raw_artifact(tenant_id=TENANT_ID, ref=ref)
    assert _RAW_MARKER in recovered


def test_artifact_gateway_put_raw_artifact_is_the_sole_write_path_hash_is_content_addressed() -> (
    None
):
    """Pins `FakeArtifactGateway.put_raw_artifact`'s content-addressing
    invariant directly (independent of the pooled-capture pipeline above):
    identical raw content always yields an identical `artifact_hash`, and
    the returned `raw_object_ref` is always scoped under the CALLING
    tenant's own namespace — never a caller-influenced/predictable-only-by-
    content path an attacker could pre-guess to read another tenant's
    artifact without ever having been granted the ref."""
    gateway = FakeArtifactGateway()
    ref_1 = gateway.put_raw_artifact(tenant_id=TENANT_ID, raw_content=_RAW_HTML)
    ref_2 = gateway.put_raw_artifact(tenant_id=TENANT_ID, raw_content=_RAW_HTML)

    assert ref_1.artifact_hash == ref_2.artifact_hash
    assert ref_1.raw_object_ref == ref_2.raw_object_ref
    assert ref_1.raw_object_ref.startswith(f"artifact://{TENANT_ID}/")
    # The ref must never itself BE (or embed) the raw bytes.
    assert _RAW_MARKER not in ref_1.raw_object_ref.encode()
    assert _RAW_MARKER not in ref_1.artifact_hash.encode()
