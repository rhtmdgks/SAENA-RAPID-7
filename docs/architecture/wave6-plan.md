# Wave 6 (Pilot Operationalization · Skill Distribution · External-Project Runner) — plan / DAG

Branch: `wave6-operationalization` (from base `main` = `68b63a2`, W5 PR #7).
Engine scope: **ChatGPT Search ONLY** (unchanged; NR-1). Date: 2026-07-19.
Author: Lead Orchestrator. This document is the W6-00 deliverable: DAG,
ownership map, integration order, acceptance matrix, risk register, and the
frozen interface contracts that let independent units proceed in parallel.

## 0. Baseline (recorded before any Wave 6 edit)

- Start: `main` = `68b63a2d6eb662ee7fcc51432e5eb9b5a14e6ea1` = `origin/main` (fetched 2026-07-19).
- Working tree clean except **untracked `.devcontainer/devcontainer-lock.json`**
  (user work; devcontainer CLI feature-pin lockfile). Wave 6 does NOT delete it
  and does NOT commit it without human direction — reported in handoff.
- `just verify` baseline: **GREEN, exit 0** — 5363 passed, 45 skipped (all
  pre-existing, documented: contract N-1 first-release tag absence; kubeconform/
  helm binaries absent on host), coverage harness 99%≥90, ratchet ok,
  import-linter 11/11 KEPT, registry/OpenAPI OK.
- Hooks: W0 5종 wired in checked-in `.claude/settings.json`; **firing evidence**:
  `audit/agent-hooks/2026-07-18.jsonl` records this session's tool calls;
  `deny-deploy-push` live-blocked a non-allowlisted `git credential` call;
  `deny-unpinned-install` consulted on installs. protect-paths = audit-only
  mode (auto-approve + audit) per prior user directive recorded in the script.
- Host: fresh machine — `just`/`shellcheck`/`gitleaks` were absent. Installed
  pinned per `.tool-versions` via hook-allowlisted `uv tool install`:
  `rust-just==1.56.0`, `shellcheck-py==0.10.0.1`. `gitleaks` NOT installed (no
  pinned uv path; CI security.yml runs it; bootstrap unit must report it as an
  optional/managed dependency honestly). Docker daemon healthy (29.4.1).
  `claude` CLI 2.1.205 (`plugin validate --strict` available).
- Inventories: agents **14** defined (`.claude/agents/**` — README states 14종),
  commands 0 (README only), hooks 5 active scripts, skills **0**
  (`.claude/skills/README.md` = NOT IMPLEMENTED; it enumerates the mandatory 16),
  runtime hook engine `packages/hooks-runtime` (w3-06).
- Open PRs: **unknown — `gh` CLI is NOT authenticated on this host.** Read
  access to origin works (https fetch OK). Risk register R-1.
- Session accommodation (documented, non-weakening): `.claude/settings.local.json`
  (gitignored, personal) sets `teammateMode: "in-process"` because this session
  is not inside iTerm2 and Agent Teams are mandated. No permission/deny/hook
  change.

## 1. Mission → unit DAG

Unit IDs follow ADR-0023 (`w6-<seq2>-<slug>`, branch `unit/<unit-id>`,
worktree `../SAENA-RAPID-7.worktrees/<unit-id>/`, exclusive-path registry via
`just worktree-create`). w6-00 (this plan) is Lead-direct on the wave branch.

| Unit | Scope (deliverable) | Exclusive paths | Depends on |
|---|---|---|---|
| w6-00 | this plan + baseline record | `docs/architecture/wave6-plan.md` | — |
| w6-01-skill-manifest | canonical manifest + JSON schema + validator + quality checker + tests | `.claude/skills/manifest.json`, `.claude/skills/manifest.schema.json`, `tools/validation/skill_manifest.py`, `tests/unit/skills_manifest/**` | interface frozen §3 (parallel-safe) |
| w6-02-skills-bootstrap | SKILL.md ×2: saena-intake, saena-security-redteam | `.claude/skills/saena-intake/**`, `.claude/skills/saena-security-redteam/**` | §3 contract |
| w6-03-skills-plan-a | SKILL.md ×2: saena-site-discovery, saena-demand-graph | `.claude/skills/saena-site-discovery/**`, `.claude/skills/saena-demand-graph/**` | §3 contract |
| w6-04-skills-plan-b | SKILL.md ×3: saena-b2b-saas-entity, saena-claim-evidence, saena-chatgpt-search | those three dirs | §3 contract |
| w6-05-skills-exec-a | SKILL.md ×2: saena-technical-aeo, ponytail | those two dirs | §3 contract |
| w6-06-skills-exec-b | SKILL.md ×2: saena-answer-capsule, saena-schema-fidelity | those two dirs | §3 contract |
| w6-07-skills-verify | SKILL.md ×5: saena-content-fidelity, saena-accessibility-visual, saena-patch-review, saena-rollback, ponytail-review | those five dirs | §3 contract |
| w6-08-bundle-enforcement | bundle validator (full-bundle/phase-order/unknown-skill fail-closed) + adversarial bypass tests | `tools/validation/skill_bundle.py`, `tests/unit/skills_bundle/**` | w6-01 integrated |
| w6-09-plugin-packaging | plugin dir + marketplace manifest + sync/drift gate | `plugins/**`, `.claude-plugin/**`, `tools/validation/skill_pack_sync.py`, `tests/unit/skill_pack/**` | w6-01..07 integrated |
| w6-10-bootstrap | `scripts/bootstrap-claude.sh` (+ `--check/--install/--json`) + corpus tests | `scripts/**`, `tools/validation/bootstrap-tests/**`, `tests/unit/bootstrap_script/**` | §3 contract |
| w6-11-pilot-core | `tools/saena-pilot/**` package: CLI 7 modes, intake/action-contract, run metadata, evidence binding, launcher; root `pyproject.toml` workspace wiring | `tools/saena-pilot/**`, `pyproject.toml`, `tests/unit/pilot/**` | §3 contract |
| w6-12-pilot-discovery | discovery adapters (Next.js/Remix/Astro/Nuxt/SvelteKit/static/unsupported) + Docker preflight | `tools/saena-pilot/src/saena_pilot/discovery/**`, `tools/saena-pilot/src/saena_pilot/docker_preflight.py`, `tests/unit/pilot_discovery/**` | w6-11 integrated |
| w6-13-pilot-security | adversarial boundary/security test battery | `tests/security/pilot/**` | w6-11 (+12) integrated |
| w6-14-pilot-e2e | synthetic fixture repos + full-lifecycle E2E + failure/resume scenarios + completeness manifest | `tests/e2e/pilot/**` | w6-11 (+12) integrated |
| w6-15-ci-gates | justfile recipes + ci.yml named gates + gate-evidence spec entries | `justfile`, `.github/workflows/ci.yml`, `tools/validation/gate_evidence_spec.py`(additive), `docs/architecture/wave6-plan.md`(no) | all test units integrated |
| w6-16-docs | runbook + README/inventory updates + requirements-matrix rows | `docs/runbooks/**`, `README.md`, `.claude/README.md`, `.claude/skills/README.md`, `docs/traceability/requirements-matrix.md` | w6-01..15 shapes final |
| w6-17-closure | integration, independent critics, rework, repeated verify, push, PR, CI watch | (Integrator/Lead; no exclusive source paths) | all |

Single-owner shared surfaces: root `pyproject.toml` → w6-11 only. `justfile` +
`.github/workflows/ci.yml` → w6-15 only (other units hand off recipe text in
their reports). `.claude/skills/README.md` → w6-16 only. Conflicts resolved by
Integrator only (CLAUDE.md p6).

Parallel wave A (now): w6-01, w6-02..07, w6-10, w6-11.
Wave B (after A integrates): w6-08, w6-09, w6-12.
Wave C: w6-13, w6-14. Wave D: w6-15, w6-16. Wave E: w6-17.

## 2. Requirements traceability (mission → unit)

- 16 mandatory SKILL.md → w6-02..07; machine-validated manifest/quality → w6-01.
- Bundle fail-closed (empty/partial/unknown/tamper/bypass) → w6-08 (+w6-13 CI gate skill-bundle-bypass).
- Plugin/marketplace + `claude plugin validate --strict` + SSOT no-drift → w6-09.
- One-command reproducible install on a new computer → w6-10 (idempotent, --check/--install/--json, spaces/Unicode, macOS/Linux tested, Windows/WSL honest-docs-only).
- External customer repo referenced-not-copied; pilot modes; dedicated customer worktree writes; evidence binding (RAPID-7 SHA, customer SHA, domain, mode, run ID, manifest version, skill bundle) → w6-11.
- Intake/action contract fail-closed → w6-11. Framework discovery + Docker preflight honesty → w6-12.
- Adversarial security matrix (path/symlink escape, shell injection, malicious customer CLAUDE.md, SSRF/localhost/metadata, secret exfiltration, cross-run contamination, replay, manifest tamper, hook disable, partial skill selection, protected-path writes, copy-into-RAPID-7) → w6-13.
- E2E fixtures (Next.js, static, dirty, spaces+Unicode, malicious, unsupported, Docker-absent, interrupt/resume) → w6-14.
- Named CI gates (skill-manifest, skill-quality, skill-bundle-bypass, plugin-validate, claude-bootstrap, pilot-path-boundary, pilot-security, pilot-e2e, pilot-failure-modes, pilot-evidence-integrity, docs-consistency) → w6-15, reusing the Wave-5 completeness/no-skip/evidence pattern (`tests/integration/_gate_evidence.py`, `gate_evidence_spec.py`, `render_gate_evidence.py`).
- Runbook with only-tested commands → w6-16 (docs-consistency gate enforces).
- Independent critics + repeated verification + push + PR + CI watch, no merge → w6-17.

## 3. Frozen interface contracts (authors code against these)

### 3.1 Skill manifest (`.claude/skills/manifest.json`) — SSOT
`schema_version: "saena.skill-manifest/v1"`; `engine_scope: ["chatgpt-search"]`
(closed enum — fa-06/fa-07 precedent); `bundle_name: "saena-forge-core"`;
`phase_order: ["bootstrap","plan","execute","verify"]`; `skills[]` each:
`name` (== dir name, kebab), `version` (semver), `phase`, `path`
(`.claude/skills/<name>/SKILL.md`), `engines` (subset of engine_scope),
`required_inputs[]`, `produces[]`, `agents[]` (subset of the 14 defined),
`depends_on[]` (names in-manifest), `safety_gates[]`, `verification_gates[]`,
`failure_behavior: "fail-closed"` (literal). Validator rejects: duplicate,
missing-on-disk, unregistered-on-disk, unknown key, malformed frontmatter,
manifest/frontmatter mismatch, unknown agent, unknown engine, dependency
cycle or cross-phase-backward dependency.

### 3.2 SKILL.md contract
YAML frontmatter: exactly `name` (== dir), `description` (trigger-front-loaded,
what+when). Body REQUIRED H2 sections (quality validator enforces presence +
non-trivial content): Purpose / When to use (trigger) / When NOT to use /
Required inputs (with validation) / Authoritative references (spec §s) /
Workflow (deterministic, numbered) / Agent delegation / Hooks & gates /
Artifacts & outputs / Evidence & provenance / Fail-closed behavior /
Untrusted content & prompt injection / Secrets & PII / Verification /
Non-goals / Examples (fixture paths & example.com-style domains only; no real
credentials or customer data). Scope-sensitive skills must state engine scope
(ChatGPT Search only; Google AI Overviews/AI Mode/Gemini forbidden) and the
enforcement-honesty note (runtime FORGE hook ladder NOT IMPLEMENTED — skills
declare, W0 dev hooks + human review enforce).

### 3.3 saena-pilot CLI
`tools/saena-pilot/` mirroring forgectl: hatchling, src-layout
(`src/saena_pilot/`), `py.typed`, argparse `main(argv) -> int`, explicit exit
codes; workspace member; invoked `uv run saena-pilot …` (console script) and
`uv run python -m saena_pilot …`. Modes: `preflight audit plan implement
verify resume status` (+ `--dry-run` rendered launch command). Required args:
`--customer-repo` (absolute), `--domain` (https), `--customer-id`; write modes
additionally require explicit `--mode implement` + allowed write scope in the
action contract. Run state: `~/.saena/pilot-runs/<run-id>/` (outside both
repos' tracked files). Customer writes: only in a dedicated customer-side
worktree `<customer>/.git` → `git worktree add <customer>.saena-worktrees/
<run-id>` branch `saena-pilot/<run-id>`. Launch = `claude --add-dir
<customer-path>` from RAPID-7 root (hooks/agents stay active), args
list-passed (no shell interpolation), every path/arg quoted. Evidence record:
`saena.pilot-evidence/v1`, sha256 chain, bound to rapid7_sha, customer_sha,
domain, mode, run_id, manifest_version, skill bundle hash.

### 3.4 New named gates (w6-15)
Each = justfile recipe (env-arm SSOT + `PYTEST_ADDOPTS=''`) + ci.yml job
(needs: unit, `uv run just <recipe>`); pilot-e2e / pilot-failure-modes /
pilot-security follow the Wave-5 evidence template (SAENA_GATE_EVIDENCE_PATH +
gate-unique SAENA_GATE_INVOCATION_ID + render_gate_evidence fail-closed +
artifact upload) with a completeness manifest so partial selection/deselection
/skip/xfail cannot go green.

## 4. Acceptance matrix (unit → required proof)

Every unit: (i) unit-specific tests green in its worktree; (ii) `just verify`
green post-integration; (iii) independent critic verdict recorded; (iv)
commit(s) on `unit/<id>` integrated onto wave branch; (v) honest handoff notes.
Unit-specific: w6-01 validator negative-corpus (dup/missing/unknown/malformed
≥8 cases); w6-02..07 pass skill-quality validator + manifest agreement;
w6-08 bypass corpus (empty/partial/unknown/env-override/direct-call ≥6);
w6-09 `claude plugin validate --strict` exit 0 + drift gate red-on-mutation
proof; w6-10 idempotence (2nd run no-op), bash+zsh, space/Unicode path, JSON
mode contract, no parent-shell kill, shellcheck clean; w6-11 mode matrix +
fail-closed intake + evidence tamper detection; w6-12 per-framework fixture
detection + Docker absent/present honesty; w6-13 every attack has an
executable test with asserted exit/status; w6-14 full lifecycle on fixtures
with RAPID-7-unchanged proof + completeness manifest; w6-15 gates fail-closed
on partial selection (demonstrated); w6-16 every documented command exercised
by a test/smoke.

## 5. Risk register

- R-1 `gh` unauthenticated → PR open/update may be human-blocked. Mitigation:
  attempt push via git credential helper; if PR API impossible, complete all
  work, push branch, report BLOCKED(human) for PR step only. No relabeling.
- R-2 `claude plugin validate` behavior differences by CLI version → validate
  with local 2.1.205, record version in evidence; CI gate uses documented
  fallback (schema self-validation) if CLI unavailable in CI — stated honestly.
- R-3 Worktree glob overlap between pilot-core and pilot-discovery → resolved
  by sequencing (w6-12 after w6-11 integration).
- R-4 Docker-heavy lanes contention → pilot E2E lanes are container-free by
  design (fixture repos + subprocess); existing container lanes serialized in
  closure verification.
- R-5 Skill authors drifting from spec → §3.2 contract + w6-01 validator +
  independent skill-quality critic in w6-17.
- R-6 protect-paths audit-only mode could let an agent write protected paths →
  agents receive explicit path ownership; Integrator inspects every commit;
  closure audit greps the wave diff against protected-paths.txt.
- R-7 Secret leakage in examples/fixtures → skill examples restricted to
  example.com-style; w6-13 secret-exfil tests; security.yml gitleaks in CI.

## 6. Conservative decisions log (documented, non-blocking)

- D-1 `scripts/bootstrap-claude.sh` at new top-level `scripts/` (mission-named
  path; `tools/bootstrap/README` says "No package installs here" so the
  installing entry point must not live there).
- D-2 saena-pilot in Python (repo-conventional; forgectl precedent), console
  script added (UX requirement `saena-pilot …`).
- D-3 Plugin canonical source = `.claude/skills/**`; installable copy under
  `plugins/saena-skill-pack/` generated by a sync tool + byte-equality drift
  gate (mission: one canonical source, no silent drift).
- D-4 `.devcontainer/devcontainer-lock.json` left untracked (user work; likely
  should be committed per ADR-0021 pinning posture — surfaced for human).
- D-5 Bundle enforcement = validator invoked at pilot start (hard fail-closed)
  + standalone gate; no weakening of existing SessionStart hooks. Any
  settings.json hook addition is deferred to human (protected surface).
- D-6 gitleaks not installed locally (no pinned uv path) — bootstrap reports
  it under "managed by CI / optional local", never claims local scan ran.

## 7. Status

W6-00 COMPLETE at commit of this file. Execution proceeding per §1 waves.
