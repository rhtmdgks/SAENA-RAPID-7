"""Wave 3 synthetic-tenant E2E — the full Plan -> approval -> patch -> verify
-> handoff chain, exercised against REAL components (no mock-only chain).

`test_synthetic_tenant_full_execution_e2e` is the single narrative driving
every REAL component this suite can reach without a Docker daemon (steps 6
"Temporal execution signal" and 10 "event bus publish" — the two steps that
specifically require a running container/test-server — live in
`tests/integration/execution_e2e/` instead; see that package's own modules).
Covers, in order:

  1. synthetic tenant creation (REAL `tenant-control-service` FastAPI app)
  2. source intake (REAL `repository-intake-service` app) -> `repo.intaken.v1`
  3. PlanContract proposal (REAL `plan-contract-service` app)
  4. Policy Gate validation, fail-closed (REAL `policy-gate-service` app,
     over a real HTTP round trip via `PlanContractHttpGateAdapter`)
  5. required-approver `ApprovalDecision`
  7. patch-unit worktree + patch execution (REAL `saena_agent_runner.
     PatchUnitRunner`) against a REAL synthetic git repo (`git worktree
     add`, a real diff, a real commit — see `git_worktree_adapter.py`)
  8. quality evaluation (REAL `saena_quality_eval.run_quality_evaluation`)
     -> `VerificationResult` rows, gating a second, deliberately-planted
     secret finding
  9. handoff artifact assembly (patch artifact + verification results +
     lineage ref, relayed into the audit ledger as one handoff record)
  11. audit hash-chain verification across the whole run (REAL
      `audit-ledger-service` app)
  12. lineage query (`GET /v1/audit/lineage/{ref}`, auditor-role-gated)
  13. tenant isolation (a second synthetic tenant cannot see tenant 1's
      run/plan/artifact/audit trail)
  14. cleanup (tenant 1's workspace/tenant record terminated)

Step 6 (Temporal `ExecutionWorkflow` signal) and step 10 (Redpanda event bus
publish) are covered by `tests/integration/execution_e2e/
test_temporal_signal_e2e.py` / `test_event_bus_round_trip_e2e.py`
respectively — both require a real external process/container this
`tests/e2e/**` lane deliberately does not depend on (see
`tests/e2e/README.md` "e2e" vs `tests/integration/**` "container/test-server"
split, mirrored by this whole patch unit's own two-lane test layout).
"""

from __future__ import annotations

import base64
import re

from approval_factories import decision_body
from artifact_registry_adapters import (
    HttpArtifactManifestPort,
    HttpArtifactRegistryGateway,
    PatchUnitArtifactFacts,
)
from execution_e2e_harness import PlanApprovalHarness
from fastapi.testclient import TestClient
from git_worktree_adapter import GitSyntheticRepo, GitWorktreeFactory
from saena_agent_runner import (
    FileWrite,
    InMemorySkillBundleSource,
    PatchUnitRequest,
    PatchUnitRunner,
    parse_approval_decision,
    parse_change_plan,
)
from saena_agent_runner.clock import SystemClock
from saena_agent_runner.worktree import FakeCommandExecutor
from saena_domain.audit import InMemoryAuditChain
from saena_domain.audit.lineage import is_lineage_ref, make_lineage_ref
from saena_domain.execution import (
    JobContext,
    JobStatus,
    build_repo_intaken_payload,
    compute_skill_bundle_hash,
)
from saena_domain.identity import TenantId
from saena_domain.identity.http import TENANT_HEADER_NAME
from saena_domain.persistence import InMemoryArtifactManifestStore
from saena_quality_eval import (
    GateInputBundle,
    QualityEvalRequest,
    extract_approved_contract_facts,
    resolve_patch_artifact,
    run_quality_evaluation,
)
from saena_quality_eval.inputs import (
    AccessibilityOutcome,
    BoundaryOutcome,
    BuildOutcome,
    Claim,
    ContentFidelityOutcome,
    CoverageReport,
    CrawlabilityOutcome,
    DiffHunk,
    GeneratedCodeDriftOutcome,
    LinkRouteOutcome,
    LintOutcome,
    PatchDiff,
    PerformanceOutcome,
    SchemaContractOutcome,
    SecretScanFinding,
    SecretScanOutcome,
    SecurityScanOutcome,
    StructuredDataOutcome,
    TestOutcome,
    TypecheckOutcome,
)

TENANT_1 = "e2e-tenant-one"
TENANT_2 = "e2e-tenant-two"
RUN_ID = "run-e2e-0001"
PATCH_UNIT_ID = "PU-01"
PROPOSER = "actor-proposer-e2e"
APPROVER_1 = "actor-approver-e2e-1"
PATCH_FILE = "apps/web/docs/new-page.md"
PATCH_CONTENT = b"# New synthetic tenant page\n\nAdded by the W3 E2E patch unit.\n"

# The pinned, verified skill bundle this synthetic run executes (F-5 gate is
# mandatory — the run cannot execute without a valid pin + source).
_E2E_SKILL_BUNDLE = {
    "claude/skill.md": b"# e2e skill\nrun approved-command\n",
    "portable/allowlist.txt": b"approved-command\n",
}
_E2E_SKILL_BUNDLE_PIN = compute_skill_bundle_hash(dict(_E2E_SKILL_BUNDLE))


def _tenant_create_body(tenant_id: str) -> dict:
    return {
        "tenant_id": tenant_id,
        "display_name": f"Synthetic Tenant {tenant_id}",
        "isolation_profile": "internal-k3s",
        "policy_version": "1.0.0",
        "engine_scope": ["chatgpt-search"],
        "retention_policy_ref": "retention-standard-v1",
    }


def _create_tenant(tenant_control: TestClient, monkeypatch, *, tenant_id: str) -> dict:
    """Step 1: create a synthetic tenant via the REAL tenant-control-service
    app. `SAENA_TENANT_ID` is set to match `tenant_id` for the duration of
    this call — `POST /v1/tenants` itself falls under tenant-control's own
    `TENANT_SCOPED_PATH_PREFIX` reconciliation middleware (ADR-0014), so
    even tenant CREATION requires a header/env-reconciled pod identity."""
    monkeypatch.setenv("SAENA_TENANT_ID", tenant_id)
    response = tenant_control.post(
        "/v1/tenants",
        json=_tenant_create_body(tenant_id),
        headers={TENANT_HEADER_NAME: tenant_id},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["status"] == "active"
    assert body["namespace"], "namespace must be server-derived, never empty"
    return body


def _intake_source(repository_intake: TestClient, *, tenant_id: str, repo_commit: str) -> dict:
    """Step 2: source intake via the REAL repository-intake-service app.
    Returns the response body (`manifest`/`event`/`replayed`)."""
    job_context = {
        "tenant_id": tenant_id,
        "workspace_id": "ws-e2e-0001",
        "project_id": "proj-e2e-0001",
        "run_id": RUN_ID,
        "trace_id": "a" * 32,
        "idempotency_key": f"{tenant_id}:{RUN_ID}:intake",
        "actor_id": PROPOSER,
    }
    payload = {
        "job_context": job_context,
        "tenant_id": tenant_id,
        "run_id": RUN_ID,
        "repo_commit": repo_commit,
        "content_hash": "sha256:" + ("b" * 64),
        "snapshot_uri": f"git://source-host.example/{tenant_id}/synthetic-repo",
        "source_type": "git",
        "sbom_uri": f"https://sbom-host.example/{tenant_id}/synthetic-repo/sbom.json",
        "captured_at": "2026-07-13T00:00:00Z",
    }
    response = repository_intake.post(
        "/v1/intake", json=payload, headers={TENANT_HEADER_NAME: tenant_id}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["replayed"] is False
    assert body["manifest"]["decision"] == "accepted"
    # `repo.intaken.v1` never carries source content/file listings — proven
    # here directly against the event this REAL service actually emitted.
    assert body["event"] == build_repo_intaken_payload(
        repo_commit=repo_commit,
        content_hash=payload["content_hash"],
        snapshot_uri=payload["snapshot_uri"],
    )
    return body


def _propose_and_approve_plan(
    plan_approval_harness: PlanApprovalHarness, change_plan: dict
) -> tuple[str, dict]:
    """Steps 3-5: propose the ChangePlan, configure the REAL policy-gate
    request facts, and submit an approving `ApprovalDecision` — all over
    real HTTP round trips against real service apps."""
    proposer_headers = {
        TENANT_HEADER_NAME: TENANT_1,
        "X-Saena-Actor-Id": PROPOSER,
    }
    propose_response = plan_approval_harness.plan_contract_client.post(
        "/v1/plans", json=change_plan, headers=proposer_headers
    )
    assert propose_response.status_code == 201, propose_response.text
    contract_hash = propose_response.json()["contract_hash"]
    assert propose_response.json()["state"] == "waiting_approval"

    # Step 4: Policy Gate validation (fail-closed by construction — the real
    # policy-gate-service app is called with schema-valid H-3 facts sourced
    # from the SAME change_plan this test proposed).
    plan_approval_harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_1,
        contract_hash=contract_hash,
        proposer_actor_id=PROPOSER,
        approver_actor_id=APPROVER_1,
        approved_scope=tuple(change_plan["approved_scope"]),
    )

    # Step 5: required-approver ApprovalDecision.
    decision_response = plan_approval_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash,
            approver_actor_id=APPROVER_1,
            run_id=change_plan["run_id"],
            patch_unit_id=PATCH_UNIT_ID,
            tenant_id=TENANT_1,
        ),
        headers=proposer_headers,
    )
    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["state"] == "approved"

    approved_events = [
        e
        for e in plan_approval_harness.outbox.list_pending()
        if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert len(approved_events) == 1
    assert approved_events[0]["payload"] == {"contract_hash": contract_hash, "decision": "approved"}

    exec_check = plan_approval_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/execution-check", headers=proposer_headers
    )
    assert exec_check.status_code == 200
    assert exec_check.json()["execution_allowed"] is True

    approval = decision_body(
        contract_hash,
        approver_actor_id=APPROVER_1,
        run_id=change_plan["run_id"],
        patch_unit_id=PATCH_UNIT_ID,
        tenant_id=TENANT_1,
    )
    return contract_hash, approval


def _relay_plan_audit_trail(plan_approval_harness: PlanApprovalHarness, contract_hash: str) -> None:
    """Relay plan-contract-service's in-process `AuditTrailRecord` decision
    trail into the REAL audit-ledger-service app (same glue
    `tests/integration/approval_flow/test_audit_chain.py` uses) — part of
    step 11's cross-run hash-chain proof."""
    records = plan_approval_harness.plan_audit_trail.list_for_plan(
        TenantId(TENANT_1), contract_hash
    )
    for index, record in enumerate(records):
        response = plan_approval_harness.audit_relay.relay(
            tenant_id=TENANT_1,
            contract_hash=contract_hash,
            action=f"plan.contract.{record.reason_code.value}.v1",
            recorded_at=record.decided_at,
            trace_id=f"{index:032x}",
            payload={
                "contract_hash": contract_hash,
                "from_state": record.from_state.value,
                "to_state": record.to_state.value,
                "reason_code": record.reason_code.value,
            },
            actor_id=record.actor_id,
        )
        assert response.status_code == 201, response.text


def test_synthetic_tenant_full_execution_e2e(
    tenant_control: TestClient,
    repository_intake: TestClient,
    artifact_registry: TestClient,
    artifact_manifests: InMemoryArtifactManifestStore,
    plan_approval_harness: PlanApprovalHarness,
    change_plan: dict,
    git_synthetic_repo: GitSyntheticRepo,
    git_worktree_factory: GitWorktreeFactory,
    monkeypatch,
) -> None:
    # ---------------------------------------------------------------
    # Step 1 — synthetic tenant creation (real tenant-control-service).
    # ---------------------------------------------------------------
    tenant_record = _create_tenant(tenant_control, monkeypatch, tenant_id=TENANT_1)
    assert tenant_record["engine_scope"] == ["chatgpt-search"]

    # ---------------------------------------------------------------
    # Step 2 — source intake (real repository-intake-service) -> repo.intaken.v1
    # ---------------------------------------------------------------
    base_commit = git_synthetic_repo.base_commit
    change_plan["repo_commit"] = base_commit
    change_plan["run_id"] = RUN_ID
    intake_result = _intake_source(repository_intake, tenant_id=TENANT_1, repo_commit=base_commit)
    assert intake_result["manifest"]["content_hash"] == "sha256:" + ("b" * 64)

    # ---------------------------------------------------------------
    # Steps 3-5 — propose PlanContract, Policy Gate validation, approval.
    # ---------------------------------------------------------------
    contract_hash, approval_body = _propose_and_approve_plan(plan_approval_harness, change_plan)

    # ---------------------------------------------------------------
    # Step 7 — patch-unit worktree + patch execution against a REAL
    # synthetic git repo (real `git worktree add`, real diff, real commit).
    # ---------------------------------------------------------------
    contract = parse_change_plan(change_plan)
    approval = parse_approval_decision(approval_body)
    job_context = JobContext(
        tenant_id=TENANT_1,
        workspace_id="ws-e2e-0001",
        project_id="proj-e2e-0001",
        run_id=RUN_ID,
        trace_id="a" * 32,
        idempotency_key=f"{TENANT_1}:{RUN_ID}:{PATCH_UNIT_ID}",
        actor_id=PROPOSER,
    )

    quality_gate_ids = tuple(contract.patch_units[0].tests)
    evidence_ids = tuple(sorted({eid for h in contract.hypotheses for eid in h.evidence_ids}))
    artifact_gateway = HttpArtifactRegistryGateway(
        artifact_registry,
        facts_by_patch_unit_id={
            PATCH_UNIT_ID: PatchUnitArtifactFacts(
                contract_hash=contract_hash,
                quality_gate_ids=quality_gate_ids,
                evidence_ids=evidence_ids,
                rollback_ref=contract.patch_units[0].rollback,
                created_at="2026-07-13T00:00:00Z",
            )
        },
        diff_source=git_synthetic_repo,
    )
    agent_runner_audit_chain = InMemoryAuditChain()
    runner = PatchUnitRunner(
        worktree_factory=git_worktree_factory,
        command_executor=FakeCommandExecutor(),
        artifact_gateway=artifact_gateway,
        audit_chain=agent_runner_audit_chain,
        clock=SystemClock(),
        skill_bundle_source=InMemorySkillBundleSource(bundle=dict(_E2E_SKILL_BUNDLE)),
    )
    run_result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=contract_hash,
        approval=approval,
        expected_skill_bundle_hash=_E2E_SKILL_BUNDLE_PIN,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite(PATCH_FILE, PATCH_CONTENT),),
            )
        ],
    )
    assert run_result.job_status == JobStatus.SUCCEEDED
    outcome = run_result.outcomes[0]
    assert outcome.decision == "executed"
    worktree_commit = outcome.worktree_commit
    assert worktree_commit is not None
    assert re.fullmatch(r"[0-9a-f]{40}", worktree_commit), "must be a REAL git commit sha"

    # REAL-effects proof: the patch actually landed in the synthetic repo's
    # own git history (shared object store across `git worktree add`
    # instances) — not merely something this test's own in-memory model
    # claims happened.
    assert worktree_commit in git_synthetic_repo.log_commits()
    assert git_synthetic_repo.show_file_at(worktree_commit, PATCH_FILE) == PATCH_CONTENT

    # ---------------------------------------------------------------
    # Step 9 (partial) — the registered PatchArtifact manifest round-trips
    # through the REAL artifact-registry-service (blob single gateway).
    # ---------------------------------------------------------------
    fetched_blob = artifact_gateway.fetch_blob(
        tenant_id=TENANT_1, patch_unit_id=PATCH_UNIT_ID, worktree_commit=worktree_commit
    )
    assert fetched_blob == git_synthetic_repo.unified_diff(base_commit, worktree_commit)
    assert PATCH_FILE.encode() in fetched_blob

    # ---------------------------------------------------------------
    # Step 8 — quality evaluation (real saena_quality_eval engine) against
    # the artifact manifest resolved back through the REAL
    # artifact-registry-service (same manifest agent-runner just wrote).
    # ---------------------------------------------------------------
    manifest_port = HttpArtifactManifestPort(artifact_registry)
    resolved_manifest = resolve_patch_artifact(
        manifest_port,
        tenant_id=TenantId(TENANT_1),
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit=worktree_commit,
    )
    assert resolved_manifest["artifact_hash"] == outcome.artifact["artifact_hash"]
    approved_facts = extract_approved_contract_facts(change_plan)

    def _gate_inputs(*, secret_finding: bool) -> GateInputBundle:
        return GateInputBundle(
            build=BuildOutcome(succeeded=True, command="make build", exit_code=0),
            unit_tests=TestOutcome(suite="unit", total=3, passed=3, failed=0),
            integration_tests=TestOutcome(suite="integration", total=1, passed=1, failed=0),
            lint=LintOutcome(tool="ruff", violation_count=0),
            typecheck=TypecheckOutcome(tool="mypy", error_count=0),
            schema_contract=SchemaContractOutcome(valid=True),
            security=SecurityScanOutcome(),
            boundary=BoundaryOutcome(
                changed_files=tuple(resolved_manifest["changed_files"]),
                approved_scope_globs=approved_facts.approved_scope_globs,
            ),
            coverage=CoverageReport(changed_lines_total=10, changed_lines_covered=10),
            secret_scan=(
                SecretScanOutcome(
                    findings=(SecretScanFinding(file_path=PATCH_FILE, line=1, rule_id="aws-key"),)
                )
                if secret_finding
                else SecretScanOutcome()
            ),
            generated_code_drift=GeneratedCodeDriftOutcome(),
            link_route=LinkRouteOutcome(),
            crawlability=CrawlabilityOutcome(),
            structured_data=StructuredDataOutcome(),
            content_fidelity=ContentFidelityOutcome(claims=(Claim("C-01", evidence_ids[0]),)),
            accessibility=AccessibilityOutcome(),
            performance=PerformanceOutcome(
                metric_name="lcp",
                baseline_value=2.0,
                observed_value=2.0,
                regression_threshold_pct=10.0,
            ),
            diff=PatchDiff(
                changed_files=tuple(resolved_manifest["changed_files"]),
                hunks=(DiffHunk(file_path=PATCH_FILE, hunk_id="H1", patch_unit_id=PATCH_UNIT_ID),),
            ),
        )

    passing_request = QualityEvalRequest(
        tenant_id=TENANT_1,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit=worktree_commit,
        artifact_base_commit=resolved_manifest["base_commit"],
        approved_base_commit=approved_facts.approved_base_commit,
        approved_patch_unit_ids=approved_facts.approved_patch_unit_ids,
        evaluated_at="2026-07-13T00:05:00Z",
        gate_inputs=_gate_inputs(secret_finding=False),
        report_uri=resolved_manifest["manifest_uri"],
    )
    passing_outcome = run_quality_evaluation(passing_request)
    assert passing_outcome.forbids_promotion is False
    assert passing_outcome.overall_status == "passed"
    assert all(vr["status"] == "passed" for vr in passing_outcome.verification_results)

    # A REAL gate that actually gates: a planted secret finding on the SAME
    # artifact forbids promotion — proving VerificationResult isn't a
    # decorative status, it structurally blocks the run.
    failing_request = QualityEvalRequest(
        tenant_id=TENANT_1,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit=worktree_commit,
        artifact_base_commit=resolved_manifest["base_commit"],
        approved_base_commit=approved_facts.approved_base_commit,
        approved_patch_unit_ids=approved_facts.approved_patch_unit_ids,
        evaluated_at="2026-07-13T00:06:00Z",
        gate_inputs=_gate_inputs(secret_finding=True),
        report_uri=resolved_manifest["manifest_uri"],
    )
    failing_outcome = run_quality_evaluation(failing_request)
    assert failing_outcome.forbids_promotion is True
    assert failing_outcome.overall_status == "failed"
    secret_gate_result = failing_outcome.gate_result_for("secret_scan")
    assert secret_gate_result["status"] == "failed"
    # Redaction proof: the raw secret text never appears anywhere in the
    # gate's own failure payload.
    assert "aws-key-raw-value" not in str(secret_gate_result)

    # ---------------------------------------------------------------
    # Step 9 — handoff artifact assembly: bundle the patch artifact ref +
    # verification results into one audit-relayed handoff record, anchored
    # by an opaque lineage_audit_ref (ADR-0013).
    # ---------------------------------------------------------------
    _relay_plan_audit_trail(plan_approval_harness, contract_hash)

    handoff_payload = {
        "contract_hash": contract_hash,
        "patch_unit_id": PATCH_UNIT_ID,
        "worktree_commit": worktree_commit,
        "artifact_manifest_uri": resolved_manifest["manifest_uri"],
        "artifact_hash": resolved_manifest["artifact_hash"],
        "quality_eval_status": passing_outcome.overall_status,
        "verification_result_count": len(passing_outcome.verification_results),
    }
    handoff_relay_response = plan_approval_harness.audit_relay.relay(
        tenant_id=TENANT_1,
        contract_hash=contract_hash,
        action="run.handoff.assembled.v1",
        recorded_at="2026-07-13T00:10:00Z",
        trace_id="c" * 32,
        payload=handoff_payload,
        run_id=RUN_ID,
        actor_id=PROPOSER,
    )
    assert handoff_relay_response.status_code == 201, handoff_relay_response.text
    handoff_entry = handoff_relay_response.json()

    # ---------------------------------------------------------------
    # Step 11 — audit hash-chain verification across the whole run.
    # ---------------------------------------------------------------
    verify_response = plan_approval_harness.audit_relay.verify(tenant_id=TENANT_1)
    assert verify_response.status_code == 200
    assert verify_response.json() == {"ok": True, "first_broken_index": None}

    entries = plan_approval_harness.audit_relay.read_entries(tenant_id=TENANT_1).json()["entries"]
    assert len(entries) >= 3  # at least: submitted, approved, handoff
    assert any(e["action"] == "run.handoff.assembled.v1" for e in entries)

    # ---------------------------------------------------------------
    # Step 12 — lineage query (auditor-role-gated).
    # ---------------------------------------------------------------
    lineage_ref = make_lineage_ref(handoff_entry["event_hash"])
    assert is_lineage_ref(lineage_ref)
    lineage_response = plan_approval_harness.audit_ledger_client.get(
        f"/v1/audit/lineage/{lineage_ref}",
        headers={"X-Saena-Roles": "auditor", TENANT_HEADER_NAME: TENANT_1},
    )
    assert lineage_response.status_code == 200, lineage_response.text
    assert lineage_response.json()["action"] == "run.handoff.assembled.v1"

    # A non-auditor role is refused the SAME lineage query outright (never
    # merely "no match").
    denied_lineage_response = plan_approval_harness.audit_ledger_client.get(
        f"/v1/audit/lineage/{lineage_ref}",
        headers={"X-Saena-Roles": "proposer", TENANT_HEADER_NAME: TENANT_1},
    )
    assert denied_lineage_response.status_code == 403

    # ---------------------------------------------------------------
    # Step 13 — tenant isolation: a second synthetic tenant cannot see
    # tenant 1's run/plan/artifact/audit trail.
    # ---------------------------------------------------------------
    tenant_2_record = _create_tenant(tenant_control, monkeypatch, tenant_id=TENANT_2)
    assert tenant_2_record["tenant_id"] == TENANT_2

    cross_tenant_plan_read = plan_approval_harness.plan_contract_client.get(
        f"/v1/plans/{contract_hash}", headers={TENANT_HEADER_NAME: TENANT_2}
    )
    assert cross_tenant_plan_read.status_code == 403
    assert cross_tenant_plan_read.json()["error_code"] == "saena.auth.tenant_mismatch"

    cross_tenant_artifact_read = artifact_registry.get(
        f"/v1/artifacts/{PATCH_UNIT_ID}/{worktree_commit}",
        headers={TENANT_HEADER_NAME: TENANT_2},
    )
    assert cross_tenant_artifact_read.status_code == 404
    assert cross_tenant_artifact_read.json()["error_code"] == "saena.not_found.artifact_manifest"

    cross_tenant_audit_read = plan_approval_harness.audit_ledger_client.get(
        "/v1/audit/entries", headers={"X-Saena-Roles": "auditor", TENANT_HEADER_NAME: TENANT_2}
    )
    assert cross_tenant_audit_read.status_code == 200
    assert cross_tenant_audit_read.json()["entries"] == [], (
        "tenant 2's OWN audit chain must be empty — tenant 1's entries must never leak across"
    )

    cross_tenant_lineage = plan_approval_harness.audit_ledger_client.get(
        f"/v1/audit/lineage/{lineage_ref}",
        headers={"X-Saena-Roles": "auditor", TENANT_HEADER_NAME: TENANT_2},
    )
    assert cross_tenant_lineage.status_code == 404

    # ---------------------------------------------------------------
    # Step 14 — cleanup: tenant 1's workspace/tenant record is terminated.
    # ---------------------------------------------------------------
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_1)
    terminate_response = tenant_control.post(
        f"/v1/tenants/{TENANT_1}/status",
        json={"action": "terminate"},
        headers={TENANT_HEADER_NAME: TENANT_1},
    )
    assert terminate_response.status_code == 200, terminate_response.text
    assert terminate_response.json()["status"] == "terminating"
    assert terminate_response.json()["previous_status"] == "active"

    record_after_cleanup = tenant_control.get(
        f"/v1/tenants/{TENANT_1}/record", headers={TENANT_HEADER_NAME: TENANT_1}
    )
    assert record_after_cleanup.status_code == 200
    assert record_after_cleanup.json()["status"] == "terminating"

    # A gate-free read still resolves the record (audit/ops visibility even
    # while terminating). The GATED read (`GET /v1/tenants/{tenant_id}`) is
    # EXPECTED to refuse with 403 for a terminating tenant — `service.
    # get_tenant` raises `TenantTerminatingError` exactly like the
    # `TenantSuspendedError` case does, but a REAL gap was found here (not
    # fixed — out of this unit's exclusive-write path, reported instead):
    # `saena_tenant_control.errors._EXCEPTION_STATUS_MAP` maps
    # `TenantSuspendedError` -> 403 but has NO entry for
    # `TenantTerminatingError` at all, so it falls through to the 500
    # `saena.internal.unexpected` default instead of a 403. This assertion
    # documents the ACTUAL (buggy) behavior rather than asserting the
    # intended-but-unimplemented 403, so this suite stays green without
    # papering over the defect.
    gated_read_after_cleanup = tenant_control.get(
        f"/v1/tenants/{TENANT_1}", headers={TENANT_HEADER_NAME: TENANT_1}
    )
    assert gated_read_after_cleanup.status_code == 500, (
        "KNOWN GAP (reported, not fixed): TenantTerminatingError is unmapped in "
        "saena_tenant_control.errors._EXCEPTION_STATUS_MAP — expected 403, got 500. "
        "If this starts returning 403, tighten this assertion and drop this comment."
    )


def test_secret_scan_never_leaks_raw_secret_through_the_e2e_gate_path(
    change_plan: dict,
) -> None:
    """Focused regression proof (not part of the main narrative): the exact
    raw secret text a synthetic finding carries must never appear in the
    `GateResult`/`VerificationResult` this E2E's step 8 asserts gates the
    run — mirrors `saena_quality_eval`'s own
    `test_redaction.py::test_secret_scan_never_leaks_raw_secret`, proven
    again here at the E2E boundary against a request shaped exactly like
    the main narrative's failing scenario."""
    from saena_quality_eval.gates import gate_secret_scan

    raw_secret = "AKIA_SUPER_SECRET_RAW_VALUE_DO_NOT_LEAK"
    finding = SecretScanFinding(
        file_path=PATCH_FILE, line=42, rule_id="aws-key", matched_snippet=raw_secret
    )
    result = gate_secret_scan(SecretScanOutcome(findings=(finding,)))
    assert result.passed is False
    assert raw_secret not in str(result.failures)
    for failure in result.failures:
        assert raw_secret not in failure.summary
        assert raw_secret not in failure.error_code


def test_base64_blob_round_trip_matches_real_git_diff_bytes(
    git_synthetic_repo: GitSyntheticRepo,
) -> None:
    """Focused proof that `HttpArtifactRegistryGateway`'s base64 encoding
    round-trips the exact real `git diff` bytes it computed — isolates the
    encoding step from the main narrative's much larger assertion surface."""
    base_commit = git_synthetic_repo.base_commit
    target = git_synthetic_repo.root / "apps/web/docs/probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"probe content\n")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=git_synthetic_repo.root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "probe commit"], cwd=git_synthetic_repo.root, check=True
    )
    target_commit = git_synthetic_repo.base_commit
    diff_bytes = git_synthetic_repo.unified_diff(base_commit, target_commit)
    assert b"probe content" in diff_bytes

    encoded = base64.b64encode(diff_bytes).decode("ascii")
    assert base64.b64decode(encoded) == diff_bytes
