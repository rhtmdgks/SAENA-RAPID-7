"""F-6 Secret exposure (k3s spec §10 row 6, failure-mode matrix `F-6`).

Fixture: a customer repository's source references `.env` (a credential
file) — either the file itself is committed, or code reads it inline. k3s:
"`.env` referenced in source → redaction and stop".

Wired against BOTH real layers the mission maps this mode to:

1. `saena_repository_intake.core.perform_intake` — secret scan PRECEDES
   acceptance (module docstring point 7: "secret scan — PRECEDES acceptance
   (`SecretScanFailedError`); a flagged snapshot is refused, redacted, no
   secret echoed, and NOTHING is persisted (no half-state)").
2. `saena_quality_eval.gates.gate_secret_scan` — a planted secret anywhere
   in a patch's diff fails the `secret_scan` Release Gate, redacted via
   `redaction.redact_secret_snippet` (rule_id/file_path/line ONLY — the
   function is structurally incapable of embedding the raw matched text).

Plus the `saena_hooks_runtime.hooks.session_start.secret_scan` fail-closed
gate (`SECRET_DETECTED` → DENY, `.env`-referencing detail redacted) as a
THIRD, session-entry-time layer — belt-and-suspenders across the whole
pipeline this mode's fixture could be encountered at.
"""

from __future__ import annotations

import pytest
from factories import build_gate_input_bundle, build_quality_eval_request
from hooks_runtime_factories import RUN_ID, TENANT_ID, TRACE_ID, TS, make_budget, make_contract
from intake_factories import (
    FakeContentHashVerifier,
    FakeSecretScanner,
    build_snapshot_payload,
)
from intake_factories import (
    build_job_context as build_intake_job_context,
)
from saena_hooks_runtime.hooks.session_start import SecretFinding, SessionStartInput, session_start
from saena_hooks_runtime.models import Decision, ReasonCode
from saena_quality_eval.engine import run_quality_evaluation
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import gate_secret_scan
from saena_quality_eval.inputs import SecretScanFinding, SecretScanOutcome
from saena_repository_intake.core import perform_intake
from saena_repository_intake.errors import IntakeManifestNotFoundError, SecretScanFailedError
from saena_repository_intake.memory import (
    InMemoryAuditSink,
    InMemoryIntakeManifestStore,
    InMemoryWorkspaceStaging,
)

LITERAL_SECRET_VALUE = "AKIA_PLANTED_DOTENV_SECRET_DO_NOT_ECHO"


def test_session_start_denies_and_redacts_dotenv_referenced_secret() -> None:
    decision = session_start(
        SessionStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            worktree_dirty=False,
            policy_signature_valid=True,
            secret_findings=(
                SecretFinding(
                    location=".env:3", rule_id="dotenv-credential", raw_value=LITERAL_SECRET_VALUE
                ),
            ),
            budget=make_budget("session_start"),
        )
    )
    assert decision.decision == Decision.DENY
    assert decision.blocked is True
    assert decision.reason_code == ReasonCode.SECRET_DETECTED
    assert ".env:3" in decision.detail
    assert LITERAL_SECRET_VALUE not in decision.detail
    assert LITERAL_SECRET_VALUE not in decision.audit.detail


def test_quality_eval_secret_scan_gate_fails_and_never_echoes_raw_snippet() -> None:
    outcome = gate_secret_scan(
        SecretScanOutcome(
            findings=(
                SecretScanFinding(
                    file_path=".env",
                    line=3,
                    rule_id="dotenv-credential",
                    matched_snippet=LITERAL_SECRET_VALUE,
                ),
            )
        )
    )
    assert outcome.gate_id == GateId.SECRET_SCAN
    assert outcome.passed is False
    failure = outcome.failures[0]
    assert failure.error_code == "saena.internal.secret_detected"
    assert LITERAL_SECRET_VALUE not in failure.summary
    for value in failure.redacted_detail.values():
        assert LITERAL_SECRET_VALUE not in value
    assert ".env:3" in failure.redacted_detail["findings"]


def test_release_gate_forbids_promotion_on_dotenv_secret_end_to_end() -> None:
    gate_inputs = build_gate_input_bundle(
        secret_scan=SecretScanOutcome(
            findings=(
                SecretScanFinding(
                    file_path=".env",
                    line=1,
                    rule_id="dotenv-credential",
                    matched_snippet=LITERAL_SECRET_VALUE,
                ),
            )
        )
    )
    request = build_quality_eval_request(gate_inputs=gate_inputs)

    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    secret_scan_result = outcome.gate_result_for(GateId.SECRET_SCAN)
    assert secret_scan_result["status"] == "failed"
    assert LITERAL_SECRET_VALUE not in str(secret_scan_result)
    assert LITERAL_SECRET_VALUE not in str(outcome.audit_records)
    assert LITERAL_SECRET_VALUE not in str(outcome.events)


def test_repository_intake_refuses_dotenv_flagged_snapshot_no_secret_echoed_no_half_state() -> None:
    # Constructed directly (not via a shared `job_context` pytest fixture) —
    # `saena_repository_intake`'s own job-context shape/defaults are distinct
    # from `saena_agent_runner`'s (this conftest already exposes a
    # `job_context` fixture for the LATTER, reused by several other modules
    # in this suite; naming this one identically would silently shadow one
    # or the other rather than being a real conflict).
    intake_job_context = build_intake_job_context()
    manifest_store = InMemoryIntakeManifestStore()
    hash_verifier = FakeContentHashVerifier()
    secret_scanner = FakeSecretScanner()
    audit_sink = InMemoryAuditSink()
    workspace = InMemoryWorkspaceStaging()

    payload = build_snapshot_payload()
    secret_scanner.flag(payload["snapshot_uri"])

    with pytest.raises(SecretScanFailedError) as excinfo:
        perform_intake(
            payload=payload,
            job_context=intake_job_context,
            hash_verifier=hash_verifier,
            secret_scanner=secret_scanner,
            manifest_store=manifest_store,
            audit_sink=audit_sink,
            workspace=workspace,
        )

    exc = excinfo.value
    assert exc.error_code == "saena.policy_denied.secret_scan_failed"
    job_error = exc.to_job_error()
    assert LITERAL_SECRET_VALUE not in job_error.summary
    for value in job_error.redacted_detail.values():
        assert LITERAL_SECRET_VALUE not in value

    # partial-state-absence: nothing persisted on refusal.
    from saena_domain.identity import TenantId

    with pytest.raises(IntakeManifestNotFoundError):
        manifest_store.get(TenantId(intake_job_context.tenant_id), payload["content_hash"])
    assert workspace.outstanding == frozenset()

    # recovery: same tenant's audit trail records exactly one "refused"
    # decision, never a partial "accepted-then-something-else" record.
    decisions = [event["decision"] for event in audit_sink.events]
    assert decisions == ["refused"]
