# agent-runner-service

| Field | Value |
|---|---|
| Service name | `agent-runner-service` |
| Bounded context | Isolated agent execution |
| Primary responsibility | 격리 worktree/container에서 Codex/Claude/Cursor adapter 실행 |
| Owned data | ephemeral run artifacts |
| Consumed contracts | Action Contract; policy lease |
| Published events | patch.unit.completed.v1 |
| Consumed events | plan.contract.approved.v1; workflow execution signals |
| Upstream dependencies | agent-orchestrator-service; policy-gate-service |
| Downstream consumers | quality-eval-service; artifact-registry-service; audit-ledger-service |
| Security boundary | ephemeral Jobs; NetworkPolicy default-deny; short-lived tokens |
| Planned runtime | Kubernetes Job (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **PARTIAL (w3-03)** — pure-domain execution core + Protocol adapters/fakes implemented; no k3s Job manifest, no real git/subprocess adapter, no HTTP surface |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.2 (Action Contract), §5.3 (proof-carrying patch unit), §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/execution-runtime.md` (shared execution-domain layer, `JobKind.AGENT_RUNNER` profile)
- `docs/decisions/ADR-0003-approval-transition-authority-path.md` (approval authority boundary this package enforces fail-closed)
- `packages/contracts/json-schema/domain/{change-plan,approval-decision,patch-artifact}/v1/*.schema.json`

## Status

**PARTIAL (w3-03)**: `saena_agent_runner` (`services/platform/agent-runner-service/src/saena_agent_runner/`)
implements the `JobKind.AGENT_RUNNER` execution core:

- ADR-0003 approval verification (`approval.py`) — fail-closed on missing/
  forged/mismatched/rejected `ApprovalDecision`, per-patch-unit granularity.
- Contract-scoped patch-unit execution (`runner.py`, `contract.py`) — only
  patch units both APPROVED and named in the `ChangePlan` itself ever run.
- Per-patch-unit isolated worktree Protocol (`worktree.py`) pinned to the
  approved base commit, with an in-memory (real-tempdir, no git/subprocess)
  fake adapter.
- File/glob scope + protected-path + diff-budget guards (`scope.py`).
- Command allowlist, default DENY, absolute structural denylist (`git push`,
  `kubectl`, `helm`, credential-file reads, ...) (`commands.py`).
- Timeout (`resource_limits_for(JobKind.AGENT_RUNNER)`) + cooperative
  cancellation (`saena_domain.execution.protocols.CancellationSignal`).
- Filesystem boundary / symlink / path-traversal rejection (`scope.py`).
- Proof-carrying `PatchArtifact` construction, manifest-ref only — never a
  direct blob write (`artifact.py`; artifact-registry-service remains the
  sole blob gateway).
- `patch.unit.completed.v1` event payload on success
  (`saena_domain.execution.build_patch_unit_completed_payload`) + an audit
  entry per decision (`audit.py`, `saena_domain.audit.InMemoryAuditChain`).
- Failure cleanup: every denial/timeout/cancellation path calls
  `WorktreeHandle.rollback()` before returning — no partial commit, no
  artifact/event, is ever produced for a failed patch unit.

Deliberately NOT in this patch unit's scope (real infrastructure, later
units): a real `git worktree`/`subprocess`-backed `WorktreeHandle`/
`CommandExecutor` adapter, the actual k3s Job manifest/ServiceAccount RBAC
binding (`deploy/**`), and any HTTP surface (this is a batch Job, not an
HTTP service — see `docs/architecture/execution-runtime.md`'s Activity ↔
k3s Job connection-seam note).
