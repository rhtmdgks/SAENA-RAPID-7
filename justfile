# SAENA RAPID-7 task runner (ADR-0010). `just verify` == the CI gate set;
# keep the two in lockstep (drift violates ADR-0018).
# just is provided by the dev group (rust-just, pinned in uv.lock):
#   uv run just <recipe>   — no host-global install required.

set shell := ["sh", "-c"]

default:
    @just --list

# One-time / after dependency changes
setup:
    uv sync --locked

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run mypy

# w2-20 (Wave 2 exit): deterministic lane only — `-m "not integration"`
# excludes every test under tests/integration/** (auto-marked by that tree's
# own tests/integration/conftest.py). This is the blocking recipe `verify`
# runs: unit + contract only, no real Temporal test-server / testcontainers
# processes, so no cross-suite process contention -> no flake (root-caused
# and fixed w2-20; see tests/integration/conftest.py docstring and
# docs/architecture/testing-strategy.md "Two-lane test execution").
test:
    uv run pytest -q -m "not integration" --cov --cov-report=xml --cov-report=term:skip-covered

# w2-20: the OTHER lane — real Temporal time-skipping test-server +
# testcontainers postgres/redpanda, run serially and separately from `test`
# above so real-external-process contention never leaks into the blocking
# gate. NOT part of `verify` (local convenience + CI's separate serial job,
# ADR-0018 two-lane note) — run explicitly, or in CI as its own job.
test-integration:
    uv run pytest -q -m integration -p no:cacheprovider

# W3 named required-check recipes (ADR-0018 stable check names). These are
# TARGETED subsets used as their own CI jobs for fast, individually-named
# signal; the comprehensive `test-integration` umbrella above still runs the
# same container tests (deliberate belt-and-suspenders — the named jobs are
# the stable required checks, the umbrella is the catch-all). Unit-lane
# subsets (evals, security) also run inside `test` — re-running them here as
# named checks costs nothing (no container) and never counts twice toward
# the coverage ratchet (these invocations pass no --cov).
test-evals:
    uv run pytest tests/unit/evals_harness -q

test-failure-modes:
    uv run pytest tests/security -q
    uv run pytest -q -m integration tests/integration/failure_modes -p no:cacheprovider

test-execution-e2e:
    uv run pytest tests/e2e/execution -q
    uv run pytest -q -m integration tests/integration/execution_e2e -p no:cacheprovider

# W4 named required-check recipes (ADR-0018 stable check names; wave4-plan §99).
# Same belt-and-suspenders shape as the W3 named checks above: targeted subsets
# used as their own CI jobs; the `test`/`test-integration` umbrellas still run
# the same tests. Container legs honest-skip when Docker/driver is absent.
test-intelligence-e2e:
    uv run pytest tests/e2e/intelligence -q
    uv run pytest -q -m integration tests/integration/intelligence_e2e -p no:cacheprovider

test-storage-integration:
    uv run pytest -q -m integration tests/integration/clickhouse tests/integration/vector tests/integration/intelligence_pipeline -p no:cacheprovider

test-browser-observer:
    uv run pytest tests/unit/svc_chatgpt_observer -q

test-qeeg-replay:
    uv run pytest tests/unit/domain_qeeg tests/unit/svc_claim_evidence -q
    uv run pytest -q -m integration tests/integration/intelligence_failure -p no:cacheprovider

test-experiment-integrity:
    uv run pytest tests/unit/domain_experiment -q
    uv run pytest -q -m integration tests/integration/intelligence_failure/test_experiment_ledger_tamper.py -p no:cacheprovider

# ---- Wave 4 REMEDIATION named required checks (ADR-0018 stable check names) ----
# Concurrency/integrity/privacy gates the original W4 CI missed. Container legs
# honest-skip when Docker is unreachable; same belt-and-suspenders shape as the
# W3/W4 named checks above.

# r4-01: pgvector concurrent-upsert integrity (advisory lock + partial unique index)
vector-concurrency:
    uv run pytest tests/unit/vector_store -q
    uv run pytest -q -m integration tests/integration/vector -p no:cacheprovider

# r4-02: ClickHouse distributed idempotency (server-side dedup token, multi-writer)
# + query-time LOGICAL dedup independent of the physical window (get_* returns
# one row per (tenant_id, idempotency_key) even when a duplicate lands physically).
analytics-idempotency:
    uv run pytest tests/unit/analytics_clickhouse -q
    uv run pytest -q -m integration tests/integration/clickhouse/test_idempotency_distributed.py tests/integration/clickhouse/test_logical_dedup_beyond_window.py -p no:cacheprovider

# r4-03: experiment ledger chain-entry hash commits previous_hash (reorder/relink adversarial)
experiment-chain-adversarial:
    uv run pytest tests/unit/domain_experiment/test_ledger.py -q

# r4-04: query privacy boundary (raw query never persisted; keyed tenant-scoped ref)
intelligence-privacy:
    uv run pytest tests/unit/analytics_clickhouse/test_query_privacy.py -q
    uv run pytest -q -m integration tests/integration/clickhouse/test_query_privacy_boundary.py -p no:cacheprovider

# ---- Wave 5 (Measurement·B-Layer) named required checks (ADR-0018 stable
# check names; wave5-plan.md §"Named CI gates"). Same belt-and-suspenders
# shape as the W3/W4 named checks: targeted subsets used as their own CI
# jobs; the `test`/`test-integration` umbrellas still run the same tests.
# Container/Temporal legs honest-skip when Docker/the time-skipping server is
# absent. NOTE (w5-18 critic): the tests/security/measurement_*.py files use
# non-`test_*` filenames (helper-module convention, like measurement_fraud.py)
# so default collection SKIPS them — these gates name them EXPLICITLY so they
# actually run in CI.

# w5-03/w5-14: deployment-confirmed validation + trusted 7-day clock (domain)
# + durable Temporal timer (time-skipping integration).
measurement-clock:
    uv run pytest tests/unit/domain_measurement_clock tests/unit/svc_experiment_attribution_workflow -q
    uv run pytest -q -m integration tests/integration/measurement_workflow -p no:cacheprovider

# w5-04: measurement-time experiment binding — immutability + contamination.
experiment-registration:
    uv run pytest tests/unit/domain_measurement_binding -q

# w5-05: deterministic per-signal DiD engine.
did-attribution:
    uv run pytest tests/unit/domain_measurement_did -q

# w5-06/w5-07: outcome-layer ≥2-independent-layer B-gate + GRS fail-closed policy.
b-layer-gate:
    uv run pytest tests/unit/domain_measurement_bgate tests/unit/domain_measurement_grs -q

# w5-08/w5-09: evidence-bundle manifest (tamper-evident) + persistence ports.
evidence-bundle:
    uv run pytest tests/unit/domain_measurement_evidence tests/unit/domain_measurement_ports -q

# w5-18: cross-module privacy/tenant isolation + adversarial (non-test_* files
# named explicitly so they run) + real-Postgres persistence + ClickHouse
# outcome projection tenant isolation.
measurement-privacy:
    uv run pytest tests/security/measurement_privacy_tenant.py tests/security/measurement_adversarial.py -q
    uv run pytest tests/unit/svc_experiment_attribution_boundary -q
    uv run pytest -q -m integration tests/integration/measurement_pg tests/integration/clickhouse_outcome -p no:cacheprovider

# w5-19/c5-01: experiment-attribution boundary + fail-closed pipeline + the
# REAL composed measurement E2E (real Postgres 16 + ClickHouse 24.8 + Temporal
# time-skipping). SAENA_MEASUREMENT_E2E_REQUIRED=1 arms the required-lane guard:
# an infra-absent/all-skipped run is a HARD FAILURE (exit 6), never a silent pass.
# MUST-FIX C (defense-in-depth, belt-and-suspenders with the conftest
# completeness guard above): `PYTEST_ADDOPTS=''` on EVERY pytest line in this
# required recipe ONLY neutralizes a caller's environment (e.g.
# PYTEST_ADDOPTS="-k <test>") from shrinking this recipe's hardcoded selection
# — the env override applies to that one command each time, not the whole
# recipe/justfile, so other (non-required) recipes still honor a caller's
# PYTEST_ADDOPTS. SAENA_MEASUREMENT_E2E_REQUIRED=1 stays armed internally
# (SSOT); no `| tee` / `|| true` — the pytest exit code is the recipe line's
# exit code, untouched.
measurement-e2e:
    PYTEST_ADDOPTS='' uv run pytest tests/unit/svc_experiment_attribution_boundary tests/unit/svc_experiment_attribution_pipeline -q
    # The REAL composed E2E (w5-19/c5-01): real Postgres 16 + ClickHouse 24.8 +
    # Temporal time-skipping. SAENA_MEASUREMENT_E2E_REQUIRED=1 arms the
    # conftest's zero-collected AND all-skipped hard-fail guards (a naming
    # typo / import error / partial selection in this required lane exits 6,
    # never a silent pass); PYTEST_ADDOPTS='' strips any caller-injected
    # -k/-m/addopts so the full hardcoded path set below always runs.
    # Runtime EVIDENCE (Wave 5 evidence-integrity closure): the guard writes a
    # machine-readable saena.gate-evidence/v1 JSON here (even on failure). CI
    # sets SAENA_GATE_EVIDENCE_PATH/SAENA_GATE_INVOCATION_ID at job level so its
    # separate renderer step reads the SAME file; locally they default. The
    # CI summary is rendered FROM this file (never a static echo).
    SAENA_GATE_EVIDENCE_PATH="${SAENA_GATE_EVIDENCE_PATH:-$PWD/.evidence/gate-e2e.json}" SAENA_GATE_INVOCATION_ID="${SAENA_GATE_INVOCATION_ID:-$(uuidgen 2>/dev/null || echo local-$$)}" PYTEST_ADDOPTS='' SAENA_MEASUREMENT_E2E_REQUIRED=1 uv run pytest -q -m integration tests/integration/measurement_e2e tests/integration/measurement_workflow -p no:cacheprovider

# w5-06/w5-13/w5-18: measurement fail-closed / fraud / UNDETERMINED-never-PASS
# discriminators (named explicitly — non-test_* helper files).
# MUST-FIX C (defense-in-depth, belt-and-suspenders with the conftest
# completeness guard above): `PYTEST_ADDOPTS=''` on EVERY pytest line in this
# required recipe ONLY neutralizes a caller's environment (e.g.
# PYTEST_ADDOPTS="-k <test>") from shrinking this recipe's hardcoded selection
# — the env override applies to that one command each time, not the whole
# recipe/justfile, so other (non-required) recipes still honor a caller's
# PYTEST_ADDOPTS. SAENA_MEASUREMENT_FAILURE_REQUIRED=1 stays armed internally
# (SSOT); no `| tee` / `|| true` — the pytest exit code is the recipe line's
# exit code, untouched.
measurement-failure-modes:
    PYTEST_ADDOPTS='' uv run pytest tests/security/measurement_fraud.py tests/security/measurement_adversarial.py -q
    PYTEST_ADDOPTS='' uv run pytest tests/unit/svc_experiment_attribution_pipeline -q
    # The completed failure-mode matrix (w5-20/c5-02): real Postgres crash/
    # replay/rollback/conflict + F-9 fraud repoint through the integrated engine.
    # SAENA_MEASUREMENT_FAILURE_REQUIRED=1 arms the conftest's required-lane
    # guard: any skipped required integration test (Docker/Postgres absent) or
    # zero passed is a HARD FAILURE (exit 6) — this required gate can never pass
    # as a green "0 passed, N skipped". PYTEST_ADDOPTS='' strips any
    # caller-injected -k/-m/addopts so the full hardcoded path set always runs.
    # Runtime EVIDENCE (Wave 5 evidence-integrity closure) — see measurement-e2e.
    SAENA_GATE_EVIDENCE_PATH="${SAENA_GATE_EVIDENCE_PATH:-$PWD/.evidence/gate-failure-modes.json}" SAENA_GATE_INVOCATION_ID="${SAENA_GATE_INVOCATION_ID:-$(uuidgen 2>/dev/null || echo local-$$)}" PYTEST_ADDOPTS='' SAENA_MEASUREMENT_FAILURE_REQUIRED=1 uv run pytest -q -m integration tests/integration/measurement_failure -p no:cacheprovider

# ---- Wave 6 (Skill-Pack · Bootstrap · Pilot) named required checks (ADR-0018
# stable check names; W6-27 mission). Each recipe below is also a CI job of the
# SAME name in .github/workflows/ci.yml (job name == stable required-check
# name). Container-free + fast except pilot-e2e (armed completeness guard).
# `PYTEST_ADDOPTS=''` on every pytest line strips any caller-injected -k/-m/
# addopts so a required recipe's hardcoded selection can never be shrunk by the
# environment (defense-in-depth, same rationale as the W5 measurement gates);
# no `| tee` / `|| true` — the tool's exit code IS the recipe line's exit code.

# w6-01/02: skill-manifest SSOT — metaschema self-check + schema-conformance of
# the manifest + fail-closed structural/semantic validator + unit lane.
skill-manifest:
    uv run check-jsonschema --check-metaschema .claude/skills/manifest.schema.json
    uv run check-jsonschema --schemafile .claude/skills/manifest.schema.json .claude/skills/manifest.json
    uv run python tools/validation/skill_manifest.py validate-manifest --manifest .claude/skills/manifest.json --schema .claude/skills/manifest.schema.json
    PYTEST_ADDOPTS='' uv run pytest tests/unit/skills_manifest -q

# w6-02: SKILL.md quality contract + both-direction disk<->manifest cross-check.
skill-quality:
    uv run python tools/validation/skill_manifest.py validate-skills --manifest .claude/skills/manifest.json --skills-root .claude/skills

# w6-03: fail-closed skill-bundle enforcement (no bypass env/flag) + unit lane.
skill-bundle-bypass:
    PYTEST_ADDOPTS='' uv run pytest tests/unit/skills_bundle -q
    uv run python tools/validation/skill_bundle.py enforce

# w6-09: plugin/marketplace validation. The ENFORCING layer is the drift +
# structural gate (skill_pack_sync check = byte-equality both directions +
# manifest consistency, plus the skill_pack unit lane) — that runs unconditionally
# and needs no external binary. `claude plugin validate` is an ADDITIONAL
# structural check that only runs when the claude CLI is present; it is absent in
# most CI images (ADR-0021 pins GitHub Actions, not the claude binary), so the
# recipe guards it and never gates on its absence (plan R-2).
plugin-validate:
    uv run python tools/validation/skill_pack_sync.py check
    PYTEST_ADDOPTS='' uv run pytest tests/unit/skill_pack -q
    if command -v claude >/dev/null 2>&1; then claude plugin validate .claude-plugin/marketplace.json; else echo "claude CLI not present in CI — drift+structural gate (line above) is the enforcing layer (plan R-2)"; fi

# w6-10: local-dev convenience — read-only bootstrap self-check. NOTE: the
# claude-cli row FAILs only when the real PATH lacks the claude binary, so
# `--check` may exit nonzero in a claude-absent environment (e.g. CI). That is
# why this recipe is the LOCAL-DEV convenience form only; the DETERMINISTIC,
# claude-independent blocking layer used by the `claude-bootstrap` CI job is the
# `bootstrap-tests` recipe below. See the ci.yml `claude-bootstrap` job: it runs
# `just bootstrap-tests` as the gating step and `bootstrap-claude.sh --check`
# only as an informational (non-gating) step.
claude-bootstrap:
    sh scripts/bootstrap-claude.sh --check

# w6-10: deterministic bootstrap corpus (shim-driven, claude-binary-independent)
# + bootstrap-script unit lane. This is the BLOCKING layer for the bootstrap
# gate in CI (the `claude-bootstrap` job runs `just bootstrap-tests`).
bootstrap-tests:
    sh tools/validation/bootstrap-tests/run-corpus.sh
    PYTEST_ADDOPTS='' uv run pytest tests/unit/bootstrap_script -q

# w6-04/05: pilot path-boundary + read-only discovery unit lanes (customer root
# stays read-only; no copy into RAPID-7).
pilot-path-boundary:
    PYTEST_ADDOPTS='' uv run pytest tests/unit/pilot tests/unit/pilot_discovery -q

# w6-06: pilot security suite — ruff clean + fail-closed / injection-as-data /
# planted-secret quarantine tests.
pilot-security:
    uv run ruff check tests/security/pilot
    PYTEST_ADDOPTS='' uv run pytest tests/security/pilot -q

# w6-07/08: the composed pilot E2E. SAENA_PILOT_E2E_REQUIRED=1 ARMS the
# completeness guard: a partial -k selection, zero-collected, or an all-skipped
# run is a HARD FAILURE — this required lane can never pass as a shrunk subset or
# a green "0 passed". PYTEST_ADDOPTS='' strips caller-injected addopts so the
# full tests/e2e/pilot set always runs.
pilot-e2e:
    SAENA_PILOT_E2E_REQUIRED=1 PYTEST_ADDOPTS='' uv run pytest tests/e2e/pilot -q -p no:cacheprovider

# w6-08: focused fail-closed family (UNARMED, so the -k subset below is allowed):
# bundle-fail-closed, dirty-blocks-implement, malicious-quarantined, evidence
# tamper/truncation, and resume-refused-after-drift discriminators.
pilot-failure-modes:
    PYTEST_ADDOPTS='' uv run pytest tests/e2e/pilot -q -p no:cacheprovider -k "bundle_fail_closed or dirty_blocks_implement or malicious_quarantined or tamper or truncation or resume_refused"

# w6-08: pilot evidence-chain integrity (genesis binds skill-bundle, ordered
# lifecycle events, tamper/truncation detection). The evidence tests live in
# tests/unit/pilot/test_pilot_evidence.py in the integrated tree (verified real,
# non-empty selection — `grep -n "def test_" tests/unit/pilot/test_pilot_evidence.py`).
pilot-evidence-integrity:
    PYTEST_ADDOPTS='' uv run pytest tests/unit/pilot/test_pilot_evidence.py -q

# w6-16 (docs land in the parallel unit): this recipe validates that the KEY
# documented entry points EXIST and are invocable, so a runbook/README command
# block can never reference a dead recipe/script/CLI. Scope note: docs/runbooks
# may be empty at this unit's time — the recipe still passes on these entry-point
# existence checks; w6-16's own docs-consistency test extends coverage to parse
# every command block under docs/runbooks/** + README once those docs exist.
docs-consistency:
    test -x scripts/bootstrap-claude.sh
    uv run saena-pilot --help >/dev/null
    uv run python tools/validation/skill_manifest.py --help >/dev/null
    test -f .claude-plugin/marketplace.json
    uv run just --summary | grep -q skill-manifest

# Wave-6 aggregate convenience: runs ALL 11 Wave-6 CI gates (including the armed
# pilot-e2e and the container-free-but-slower lanes). NOT part of the blocking
# `verify` — pilot-e2e's armed guard and claude-dependent checks could be red on
# a fresh machine, so only the fast always-green subset is folded into `verify`.
# Mirrors the CI job set (bootstrap gate = the deterministic `bootstrap-tests`,
# matching the `claude-bootstrap` job's gating step).
verify-w6: skill-manifest skill-quality skill-bundle-bypass plugin-validate bootstrap-tests pilot-path-boundary pilot-security pilot-e2e pilot-failure-modes pilot-evidence-integrity docs-consistency
    @echo "verify-w6: all Wave 6 CI gates green"

# Offline chart packaging gate (no cluster contact): helm lint + template +
# kubeconform static validation + forgectl §8.1 preflight.
helm-smoke:
    helm lint deploy/charts/saena-forge
    helm template smoke deploy/charts/saena-forge > /dev/null
    helm template smoke deploy/charts/saena-forge | kubeconform -strict -ignore-missing-schemas -summary
    uv run python -m saena_forgectl preflight --values deploy/charts/saena-forge/values.yaml

# ADR-0017 coverage gates (blocking): harness core >=90, changed-lines >=90,
# global no-decrease ratchet (committed baseline; manual ratchet-up in-PR).
coverage-gates:
    uv run coverage report --include="tests/contract/harness/*" --fail-under=90
    uv run diff-cover coverage.xml --compare-branch origin/main --fail-under=90
    sh tools/validation/coverage-ratchet.sh

# Module boundary contracts (dependency-policy rule 11 / ADR-0002)
boundaries:
    uv run lint-imports

# Validate all contract schemas. Honest when empty: reports the count.
contracts-validate:
    @count=$(find packages/contracts -name '*.schema.json' 2>/dev/null | wc -l | tr -d ' '); \
    if [ "$count" = "0" ]; then \
        echo "contracts-validate: no *.schema.json under packages/contracts yet (W1 delivers schemas) — nothing validated"; \
    else \
        find packages/contracts -name '*.schema.json' -print0 | xargs -0 uv run check-jsonschema --check-metaschema; \
    fi

# Codegen pipeline (w1-12, ADR-0011 SSOT split): packages/contracts (hand-edited
# JSON Schema SSOT) -> packages/schemas/saena_schemas (codegen-only pydantic v2
# models). Flag set is BINDING per CODEGEN_LOSSLESS gate verdict (Lead,
# 2026-07-12) — do not change the flags below without re-running the gate,
# WITH ONE PROVEN EXCEPTION recorded here: the gate verdict mandated
# `--type-mappings "string+date-time=string"` for format:date-time + pattern
# collisions (TypeError at validation time) but did not anticipate the
# identical failure mode for format:uuid + pattern (event-envelope's
# event_id: format uuid + a UUIDv7 pattern) — the gate's own lossless test
# (packages/schemas/tests/test_lossless.py::test_envelope_valid_fixtures_parse)
# caught this as a real TypeError parsing the ADR-0013 fixtures, so
# `string+uuid=string` was added by the same proven mechanism, narrowly
# scoped to the one additional format that collides with `pattern` in this
# contract set. Glob-driven: any new category/contract dropped under
# packages/contracts/json-schema/** is picked up automatically on the next
# run, no recipe edit required.
#
# Open-contract list ($comment: sourced from the approved plan §5 acceptance
# matrix; hardcoded here only until packages/contracts/registry.json carries a
# compat_class field per contract, w1-15 — registry.json becomes the source of
# truth at that point and this list should be replaced with a read from it).
#
# Nested-open list (mechanism A extension, Lead ruling / critic M3,
# 2026-07-12): a contract can be sealed at its own root while still declaring
# a genuinely open nested sub-object by schema design — event-envelope's
# `payload` (commonFields.payload has no additionalProperties key at all) is
# the only case in this contract set today. CONTRACT_DIR:ClassName pairs.
codegen:
    #!/bin/sh
    set -eu
    OPEN_CONTRACTS="context/workspace_context_v1 context/project_context_v1 context/site_context_v1 context/run_context_lifecycle_v1 domain/verification_result_v1 event/patch_unit_completed_v1 event/quality_gate_result_v1 event/plan_contract_proposed_v1 event/plan_contract_approved_v1 event/repo_intaken_v1 event/site_inventory_completed_v1 event/demand_graph_versioned_v1 event/entity_graph_versioned_v1 event/claim_evidence_versioned_v1 event/citation_normalized_v1 event/observation_captured_v1 event/experiment_registered_v1 event/experiment_anchored_v1 event/deployment_confirmed_v1 event/experiment_outcome_observed_v1 event/strategy_card_eligible_v1"
    NESTED_ALLOW="envelope/event_envelope_v1:Payload"
    PKG_ROOT=packages/schemas/saena_schemas
    rm -rf "$PKG_ROOT"/context "$PKG_ROOT"/domain "$PKG_ROOT"/event "$PKG_ROOT"/envelope "$PKG_ROOT"/common
    # Package-identity __init__.py has no source schema to derive from (it is
    # not a contract) but is still recipe-written, not hand-edited (critic S3
    # narrows the packages/schemas/README.md hand-edit exception to
    # pyproject.toml + py.typed only).
    printf '%s\n' \
        '# GENERATED by tools/validation codegen recipe (justfile codegen) - DO NOT EDIT' \
        '"""saena_schemas -- codegen-only typed contract models (ADR-0011 SSOT split).' \
        '' \
        'Do not hand-edit anything under this package except pyproject.toml and' \
        'py.typed (packaging scaffolding exception, packages/schemas/README.md).' \
        'Every module here, including this file, is regenerated by the codegen' \
        'justfile recipe from packages/contracts -- see' \
        'tools/validation/codegen-patch-openroot.py.' \
        '"""' \
        '' \
        '__version__ = "0.1.0"' \
        > "$PKG_ROOT/__init__.py"
    for schema in packages/contracts/json-schema/*/*/v*/*.schema.json; do
        [ -e "$schema" ] || continue
        category=$(echo "$schema" | cut -d/ -f4)
        name=$(echo "$schema" | cut -d/ -f5)
        major=$(echo "$schema" | cut -d/ -f6)
        module_name=$(echo "$name" | tr '-' '_')_${major}
        out_dir="$PKG_ROOT/$category/$module_name"
        mkdir -p "$PKG_ROOT/$category"
        rm -rf "$out_dir"
        uv run datamodel-codegen \
            --input "$schema" \
            --input-file-type jsonschema \
            --output-model-type pydantic_v2.BaseModel \
            --target-python-version 3.12 \
            --schema-version 2020-12 \
            --use-annotated \
            --allow-remote-refs \
            --type-mappings "string+date-time=string" "string+uuid=string" \
            --custom-file-header "# GENERATED by datamodel-code-generator — DO NOT EDIT" \
            --output "$out_dir"
        # Normalize: dmcg writes a single FILE (not a package dir) when the
        # contract has no cross-file $ref that needs its own submodule. Wrap
        # it into <name>_vN/__init__.py so every contract is a uniform module.
        if [ -f "$out_dir" ]; then
            tmp="${out_dir}.tmp_pkg"
            mkdir -p "$tmp"
            mv "$out_dir" "$tmp/__init__.py"
            mv "$tmp" "$out_dir"
        fi
        touch "$PKG_ROOT/$category/__init__.py"
    done
    OPEN_ARGS=""
    for c in $OPEN_CONTRACTS; do
        OPEN_ARGS="$OPEN_ARGS --open $c"
    done
    for n in $NESTED_ALLOW; do
        OPEN_ARGS="$OPEN_ARGS --nested-allow $n"
    done
    uv run python3 tools/validation/codegen-patch-openroot.py "$PKG_ROOT" $OPEN_ARGS
    uv run ruff format "$PKG_ROOT"
    uv run ruff check --fix "$PKG_ROOT"

# Drift gate (ADR-0018): regenerate and fail if committed packages/schemas
# output differs from a fresh codegen run. `git diff --exit-code` alone only
# catches drift in already-tracked files — a NEW generated module (untracked)
# would pass silently. `git status --porcelain` also reports untracked paths,
# so it is the check that actually closes that hole (critic M1, 2026-07-12).
codegen-check: codegen
    git diff --exit-code -- packages/schemas
    test -z "$(git status --porcelain -- packages/schemas)"

# Local gate — mirrors CI (ADR-0018). The Wave-6 additions
# (skill-manifest/skill-quality/skill-bundle-bypass/plugin-validate/
# pilot-path-boundary) are the FAST, container-free, always-green-locally subset
# of the W6 gate set; the slower / armed / claude-dependent W6 gates (pilot-e2e,
# pilot-security, bootstrap-tests, etc.) run via `just verify-w6`, not here, so
# `verify` never goes red on a fresh machine.
verify: lint typecheck test coverage-gates boundaries contracts-validate registry-validate skill-manifest skill-quality skill-bundle-bypass plugin-validate pilot-path-boundary
    @echo "verify: all local gates green"

# Worktree lifecycle (ADR-0023)
worktree-create unit +args:
    sh tools/development/worktree.sh create {{unit}} {{args}}

worktree-destroy unit:
    sh tools/development/worktree.sh destroy {{unit}}

worktree-audit:
    sh tools/development/worktree.sh audit

# Tier-2 local profile (defined W0, used from W2A — ADR-0022)
dev-up +services:
    @test -f tools/development/docker-compose.dev.yaml || { echo "dev-up: tools/development/docker-compose.dev.yaml not present yet (T15/W2A)"; exit 1; }
    docker compose -f tools/development/docker-compose.dev.yaml up -d {{services}}

registry-validate:
    uv run check-jsonschema --schemafile packages/contracts/registry.schema.json packages/contracts/registry.json
    uv run openapi-spec-validator packages/contracts/openapi/contract-validation/v1/openapi.yaml

# AsyncAPI CLI smoke — pinned-limitation check (see tools/contract-lint/README.md).
# Blocking AsyncAPI gate = pytest tests/contract/validate (2020-12-real).
contract-lint-smoke:
    @out=$(SUPPRESS_NO_CONFIG_WARNING=1 npx --prefix tools/contract-lint asyncapi validate packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml --diagnostics-format=json 2>/dev/null || true); \
    echo "$out" | uv run --no-project python3 tools/contract-lint/check_known_limitation.py
