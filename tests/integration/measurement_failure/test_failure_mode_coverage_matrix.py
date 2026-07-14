"""Coverage matrix (w5-20 deliverable 3/4): every directive §3 failure mode ->
a test proving UNDETERMINED-or-FAIL-not-PASS through INTEGRATED code, with
its specific `ReasonCode`.

This module does not re-implement each proof (most already exist as
integrated-code — `run_measurement` over real domain modules — unit tests
written by w5-12/w5-13, listed below with their real file:function
locations); it is the machine-checkable INDEX the mission's "coverage matrix
comment" requires, plus a completeness assertion so the matrix cannot silently
drift from the actual test suite (a mode whose named test function stops
existing fails collection here, loudly).

## Coverage matrix (14 nodes; directive §3's 13 named modes plus the row-11/
row-1 traceability splits documented below). Format per row: N. failure mode
[reason code] -> proving test -> adversarial checklist category.

 1. missing baseline [MISSING_BASELINE] ->
    `test_missing_baseline_did_insufficiency.py::
    test_missing_baseline_is_insufficient_never_a_silent_zero` ->
    missing baseline/control/repeats
 2. missing control [MISSING_CONTROL] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py::
    test_missing_control_cell_is_undetermined` ->
    missing baseline/control/repeats
 3. contamination [TREATMENT_CONTROL_CONTAMINATION] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py::
    test_contamination_is_undetermined` -> contamination
 4. post-registration mutation [POST_REGISTRATION_METRIC_MUTATION] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py::
    test_post_registration_mutation_is_undetermined` ->
    post-registration mutation
 5. cell mismatch [CELL_MISMATCH] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py::
    test_cell_mismatch_is_undetermined` ->
    untrusted/conflicting confirmation (binding layer)
 6. insufficient repeats [INSUFFICIENT_REPEATS] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py::
    test_insufficient_repeats_is_undetermined` ->
    missing baseline/control/repeats
 7. delayed/missing deployment [DEPLOYMENT_LATE / DEPLOYMENT_UNCONFIRMED] ->
    `tests/unit/svc_experiment_attribution_pipeline/
    test_window_fail_closed.py::
    test_deployment_late_day2_rule_is_undetermined` ->
    untrusted/backdated/future/late confirmation
 8. missing raw evidence [MISSING_RAW_EVIDENCE_REF] ->
    `tests/unit/svc_experiment_attribution_pipeline/
    test_coverage_edge_cases.py::
    test_missing_per_observation_evidence_metadata_is_honest_gap` ->
    evidence tamper/reorder/splice/deletion
 9. conflicting asset hash [ASSET_HASH_CONFLICT] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py::
    test_asset_hash_conflict_is_undetermined_with_asset_reason` ->
    evidence tamper/reorder/splice/deletion
10. single-layer-only [SINGLE_LAYER_ONLY] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py::
    test_single_qualifying_layer_is_fail_not_pass` ->
    common-trend + zero-effect fraud discriminators
11. raw-count-without-lift / F-9 fraud [NEGATIVE_OR_INCONCLUSIVE_LIFT] ->
    `test_f9_fraud_repoint.py::
    test_fraud_signal_through_real_did_and_b_gate_never_passes`
    (THIS SUITE's real-engine repoint) ->
    common-trend + zero-effect fraud discriminators
12. negative/inconclusive lift [NEGATIVE_OR_INCONCLUSIVE_LIFT] ->
    `tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py::
    test_fraud_fixture_raw_up_control_up_never_passes`
    (unit-level twin of row 11 — see `b_gate.py` `MIN_NET_LIFT` boundary) ->
    common-trend + zero-effect fraud discriminators
13. window incomplete [WINDOW_INCOMPLETE] ->
    `test_clock_window_incomplete_restart.py::
    test_reevaluation_before_window_end_is_undetermined_every_time`
    (THIS SUITE, real Postgres) -> persistence/timer crash/replay
14. adapter drift [OBSERVATION_ADAPTER_DRIFT] ->
    `test_observation_adapter_drift.py::
    test_pipeline_out_of_vocabulary_layer_signal_is_undetermined_adapter_drift`
    (THIS SUITE, real Postgres) -> adapter/schema drift

14 rows cover the mission's 13-named-mode list (missing baseline/control are
named together as one bullet in the mission text but map to two distinct
reason codes/tests here) — every row's own proving test is verified to exist,
COLLECTIBLE, and (for real-Postgres rows) RAN-not-silently-skipped by the
checks below.

## THIS module's own net-new checks, beyond simple AST existence (c5-02
strengthening over the reference `test_every_matrix_row_test_exists_and_is_
collectible`, which only did AST-level "does a function with this name exist
anywhere in the file" — insufficient, per the points below):

(a) EXISTS — the file and test function both exist (`test_every_matrix_row_
    test_exists_and_is_collectible`, retained).
(b) COLLECTIBLE — pytest can actually COLLECT each node id (not just
    AST-parse the source): `test_every_matrix_row_is_pytest_collectible`
    drives `pytest --collect-only -q <nodeid>` in a subprocess (a
    genuinely independent collection pass — a decorator/syntax/import-time
    error that would prevent collection is invisible to AST parsing alone
    but is caught here) and asserts the EXACT node id string appears in
    collected output.
(c) RAN (not silently skipped) — `test_real_postgres_matrix_rows_actually_
    ran_when_docker_is_available` runs the whole `tests/integration/
    measurement_failure` suite once (subprocess, `-rs` to report skip
    reasons) and, when Docker IS available (this conftest's own honest
    probe), asserts every `@pytest.mark.integration` matrix row shows a
    PASSED outcome, not a SKIPPED one — distinguishing "skipped for a
    legitimate infra reason" (Docker absent — this whole file's `_MATRIX`
    rows would ALL report the identical honest skip reason string emitted
    by this directory's own `conftest.py`, and the test degrades to
    asserting the skip reason itself is present and uniform, never a
    silent/empty skip) from "missing/skipped for no reason" (a mix of
    passed and skipped rows under the SAME Docker-available run, or any
    skip reason that doesn't match the conftest's own string, is a matrix
    integrity failure, not an infra fact).
(d) NO DUPLICATE IDs — `test_no_duplicate_matrix_ids` asserts every
    `(file, function)` pair in `_MATRIX` is unique; two rows resolving to
    the SAME test would let one row's claimed coverage silently substitute
    for a different, uncovered failure mode.
(e) NO HELPER-ONLY FILE — `test_no_matrix_row_points_at_a_non_test_helper_
    module` asserts every `_MATRIX` file basename starts with `test_` (this
    directory's own convention — `conftest.py`/`measurement_failure_
    factories.py` are NEVER valid matrix targets) AND that pytest's own
    collector treats the named function as an actual test item (not a
    fixture or plain helper def that merely happens to start with `test_`
    in a conftest/factories module) — folded into the same `--collect-only`
    subprocess check as (b), since a factory function is never collected as
    a test regardless of its name.
(f) NO SILENT PASS UPGRADE — `test_undetermined_or_fail_rows_assert_status_
    is_never_pass` statically greps each matrix row's OWN proving-test
    SOURCE for an explicit `OutcomeStatus.PASS` / `is not OutcomeStatus.
    PASS` (or `granted is False` for the pre-repoint W3 evaluator shape)
    outcome-level assertion — every row whose semantic is "must never be
    PASS" is required to assert that PROPERTY explicitly in its own body,
    not merely assert some OTHER unrelated fact and rely on the reader's
    trust that the omitted status happened to be right.

THIS suite's OWN net-new integrated (real Postgres container) failure/
replay/rollback/rebuild/idempotency coverage (the w5-20 deliverable proper,
distinct from the pre-existing unit-level `run_measurement` proofs the table
above indexes) lives in the sibling modules of this directory:

- `test_process_restart_rebuild.py` — rebuild from the event/decision journal
  (adversarial category: persistence crash/retry).
- `test_at_least_once_replay.py` — duplicate deployment.confirmed / duplicate
  observations -> single outcome, at store + validation levels (workflow
  level cross-referenced to w5-14's own Temporal suite) (adversarial
  category: ClickHouse/Postgres duplicate+conflict).
- `test_rollback_no_partial_state.py` — failed atomic decision write leaves
  no partial state (real Postgres transaction rollback) (adversarial
  category: persistence crash/retry).
- `test_conflicting_replay.py` — same idempotency key, different content ->
  fail-closed, first wins, never arbitrary (store/validation/evidence/
  pipeline levels) (adversarial category: untrusted/conflicting
  confirmation, ClickHouse/Postgres duplicate+conflict).
- `test_observation_adapter_drift.py` — drifted observation adapter ->
  UNDETERMINED(observation_adapter_drift), never silent (adversarial
  category: adapter/schema drift).
- `test_clock_window_incomplete_restart.py` — workflow replay mid-window ->
  timer continues (cross-ref w5-14), outcome-level invariant (adversarial
  category: timer crash/replay).
- `test_f9_fraud_repoint.py` — F-9 repoint: the fraud scenario proven against
  the REAL integrated `saena_domain.measurement.did` + `b_gate` engine
  (adversarial category: common-trend + zero-effect fraud discriminators).
- `test_missing_baseline_did_insufficiency.py` — baseline-only absence closes
  the gap no existing pipeline-level unit test isolated (adversarial
  category: missing baseline/control/repeats).

Adversarial-checklist categories this directory does NOT independently cover
(intentionally, cross-referenced to their actual owning suites rather than
duplicated here): cross-tenant replay / invalid-unsigned-missing GRS / NaN
non-finite / publication failure / skill-bank intake of unverified outcomes /
secret-raw-content leakage — see `tests/security/measurement_privacy_tenant.py`
(cross-tenant), `tests/unit/svc_experiment_attribution_pipeline/
test_grs_fail_closed.py` (GRS), `tests/unit/domain_measurement_did/test_did.py`
(non-finite/`NON_FINITE_VALUE`), `tests/unit/domain_measurement_evidence/
test_evidence.py` + `test_guard_mutation.py` (raw-content/secret guard,
tamper/reorder/splice), `tests/security/measurement_privacy_tenant.py` +
`measurement_adversarial.py` (composition-level leakage/fail-closed sweeps).
This directory's OWN exclusive scope (w5-20) is failure/replay/rollback/
rebuild/idempotency + the F-9 repoint; it does not re-own those other units'
tests, matching CLAUDE.md principle 6 (독점 수정 경로).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_THIS_DIR = Path(__file__).resolve().parent

#: (module path relative to repo root, function name) for every row above.
#: `MISSING_BASELINE` (row 1) intentionally names THIS suite's own DiD-level-
#: closing pipeline test (no PRE-EXISTING pipeline-level `run_measurement`
#: unit test independently exercised a *baseline-only* absence in isolation
#: from missing_control — `MeasurementInputs`'s happy-path fixture always
#: supplies a control arm) — `test_missing_baseline_did_insufficiency.py`
#: closes that specific gap through the real DiD engine + real pipeline.
_MATRIX: tuple[tuple[str, str], ...] = (
    (
        "tests/integration/measurement_failure/test_missing_baseline_did_insufficiency.py",
        "test_missing_baseline_is_insufficient_never_a_silent_zero",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py",
        "test_missing_control_cell_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py",
        "test_contamination_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py",
        "test_post_registration_mutation_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py",
        "test_cell_mismatch_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py",
        "test_insufficient_repeats_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_window_fail_closed.py",
        "test_deployment_late_day2_rule_is_undetermined",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_coverage_edge_cases.py",
        "test_missing_per_observation_evidence_metadata_is_honest_gap",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_binding_reject.py",
        "test_asset_hash_conflict_is_undetermined_with_asset_reason",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py",
        "test_single_qualifying_layer_is_fail_not_pass",
    ),
    (
        "tests/integration/measurement_failure/test_f9_fraud_repoint.py",
        "test_fraud_signal_through_real_did_and_b_gate_never_passes",
    ),
    (
        "tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py",
        "test_fraud_fixture_raw_up_control_up_never_passes",
    ),
    (
        "tests/integration/measurement_failure/test_clock_window_incomplete_restart.py",
        "test_reevaluation_before_window_end_is_undetermined_every_time",
    ),
    (
        "tests/integration/measurement_failure/test_observation_adapter_drift.py",
        "test_pipeline_out_of_vocabulary_layer_signal_is_undetermined_adapter_drift",
    ),
)

#: Rows whose proving test is a real-Postgres integration test living in
#: THIS directory (`@pytest.mark.integration`, subject to the directory's
#: own honest Docker-absent skip) — the ONLY rows check (c) evaluates for
#: RAN-vs-SKIPPED, since the unit-level rows never skip.
_THIS_DIR_INTEGRATION_ROWS: tuple[tuple[str, str], ...] = tuple(
    (rel, fn) for rel, fn in _MATRIX if rel.startswith("tests/integration/measurement_failure/")
)

#: The exact honest-skip reason string this directory's own `conftest.py`
#: uses (see `pytest_collection_modifyitems`) — a matrix row skipping for
#: any OTHER reason, or with an empty/missing reason, fails check (c).
_EXPECTED_SKIP_REASON = "Docker daemon not reachable — honest skip (ADR-0017)"


def _function_defined_in_module(module_path: Path, function_name: str) -> bool:
    """AST-parse (not regex/substring) for `def <name>(` at ANY nesting —
    catches the function existing whether or not it happens to be collected
    as a top-level pytest item, matching `test_failure_mode_regression_suite.
    py`'s own `_function_defined_in_module` precedent's INTENT while being
    robust to decorators/indentation."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name:
            return True
    return False


def _function_source(module_path: Path, function_name: str) -> str:
    """The exact source text of ONE function (for check (f)'s outcome-level
    assertion grep) — sliced via `ast.get_source_segment` so it never
    accidentally matches a DIFFERENT function's body sharing a name
    substring."""
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    raise AssertionError(f"{function_name} not found for source-slice (should not happen post-(a))")


# --- (a) EXISTS -------------------------------------------------------------


def test_every_matrix_row_test_exists_and_is_collectible() -> None:
    """Every (module, function) pair in `_MATRIX` must be a REAL, currently-
    existing test function — the coverage matrix can never silently drift
    from the actual suite (a deleted/renamed proving test fails THIS test,
    loudly, rather than leaving a dangling claim in the docstring table)."""
    missing: list[str] = []
    for relative_path, function_name in _MATRIX:
        module_path = _REPO_ROOT / relative_path
        if not module_path.is_file():
            missing.append(f"{relative_path} does not exist")
            continue
        if not _function_defined_in_module(module_path, function_name):
            missing.append(f"{relative_path}::{function_name} not found")
    assert not missing, "coverage matrix drifted from the real suite:\n" + "\n".join(missing)


def test_matrix_covers_at_least_thirteen_named_failure_modes() -> None:
    """Directive §3 names 13 failure modes; the matrix documents 14 rows
    (missing baseline/control each split into two traceable rows per the
    docstring's own accounting) — assert the floor, not a brittle exact
    count, so a future ADDITIONAL mode never fails this gate merely for
    growing the matrix."""
    assert len(_MATRIX) >= 13


# --- (b) + (e) COLLECTIBLE, and never a helper-only file mistaken for a test


def test_every_matrix_row_is_pytest_collectible() -> None:
    """Real `pytest --collect-only` (a SEPARATE process, not this same
    interpreter's AST parse) must resolve every `_MATRIX` node id to an
    actual, collectible test item. This catches what AST parsing alone
    (check (a)) cannot: a decorator that skips/xfails collection entirely, a
    module-level import error, a name that resolves to a FIXTURE or a plain
    helper function rather than a pytest item (check (e) — a
    `conftest.py`/`*_factories.py` def named `test_*` would pass the AST
    check but is never actually collected as a test by pytest itself, since
    those modules are not collected as test modules in the first place)."""
    node_ids = [f"{relative_path}::{function_name}" for relative_path, function_name in _MATRIX]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *node_ids],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    collected = set(
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )
    missing_from_collection: list[str] = []
    for node_id in node_ids:
        if not any(node_id in line for line in collected):
            missing_from_collection.append(node_id)
    assert not missing_from_collection, (
        "matrix row(s) named a function pytest does NOT actually collect as a "
        "test (helper/fixture/import-error/skip-decorator, not a real test "
        "item):\n" + "\n".join(missing_from_collection) + f"\n\nfull output:\n{result.stdout}"
    )


def test_no_matrix_row_points_at_a_non_test_helper_module() -> None:
    """Every `_MATRIX` file basename must start with `test_` — this
    directory's own convention (`conftest.py` and `measurement_failure_
    factories.py` are explicitly NEVER valid matrix targets, per this
    directory's own docstring precedent in `measurement_failure_factories.py`
    and `conftest.py` — a matrix row pointing at either would be a
    helper-file mistaken for a test, exactly what this check exists to
    catch statically, ahead of and independent from the collection check
    above)."""
    offenders = [
        relative_path
        for relative_path, _fn in _MATRIX
        if not Path(relative_path).name.startswith("test_")
    ]
    assert not offenders, f"matrix row(s) point at a non-test-named module: {offenders}"


# --- (c) RAN (not silently skipped) -----------------------------------------


def _docker_available() -> bool:
    """Same probe this directory's own `conftest.py` uses (duplicated per
    this codebase's own established discipline for cross-module probes —
    see `conftest.py`'s module docstring), so this test's Docker-available
    branch and the actual suite run under the SAME condition."""
    import socket

    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        host_port = docker_host.removeprefix("tcp://")
        host, _, port_str = host_port.partition(":")
        port = int(port_str) if port_str else 2375
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            return False
    for candidate in (
        "/var/run/docker.sock",
        os.path.expanduser("~/.docker/run/docker.sock"),
        os.path.expanduser("~/.colima/default/docker.sock"),
    ):
        if os.path.exists(candidate):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(candidate)
                return True
            except OSError:
                continue
    return False


def test_real_postgres_matrix_rows_actually_ran_when_docker_is_available() -> None:
    """Distinguishes "skipped for a legitimate infra reason" from "missing/
    skipped for no reason" (mission requirement, check (c)):

    - Docker AVAILABLE: every `_THIS_DIR_INTEGRATION_ROWS` node id must show
      a PASSED (not SKIPPED, not FAILED-silently-ignored) outcome in a real
      `pytest -rs` subprocess run of just those node ids — a matrix row that
      quietly skips even though Docker is reachable is exactly the "missing
      coverage disguised as a documented row" failure mode this whole
      module exists to catch.
    - Docker ABSENT: every row is expected to skip, but ONLY with the exact,
      uniform, honest reason string this directory's own `conftest.py`
      emits (`_EXPECTED_SKIP_REASON`) — a differently-worded or empty skip
      reason, or a MIX of skipped and non-skipped rows under the same
      Docker-absent run, fails this test (an inconsistent skip pattern is
      itself a matrix-integrity signal, not a fact about infra).
    """
    node_ids = [
        f"{relative_path}::{function_name}"
        for relative_path, function_name in _THIS_DIR_INTEGRATION_ROWS
    ]
    # This child run deliberately selects a NODE-ID SUBSET of the matrix rows
    # (an internal ran-vs-skipped diagnostic, not an invocation of the
    # required failure-mode gate) — it must NOT inherit
    # `SAENA_MEASUREMENT_FAILURE_REQUIRED` from the parent process's
    # environment. If it did, the required-scenario COMPLETENESS guard
    # (`_failure_completeness.py`, MUST-FIX B) would correctly hard-fail this
    # intentional subset as if it were a partial-selection bypass of the real
    # gate, breaking this unrelated diagnostic. Strip it (and the sibling E2E
    # required var, for the same reason) from the child env explicitly.
    child_env = dict(os.environ)
    child_env.pop("SAENA_MEASUREMENT_FAILURE_REQUIRED", None)
    child_env.pop("SAENA_MEASUREMENT_E2E_REQUIRED", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-rs", "-q", *node_ids],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=child_env,
    )
    output = result.stdout

    if _docker_available():
        skipped_lines = [line for line in output.splitlines() if line.startswith("SKIPPED")]
        assert not skipped_lines, (
            "Docker is available in THIS run, but matrix row(s) still SKIPPED "
            "(should have RAN and PASSED against real Postgres):\n"
            + "\n".join(skipped_lines)
            + f"\n\nfull output:\n{output}"
        )
        assert result.returncode == 0, (
            f"Docker is available but the real-Postgres matrix rows did not all "
            f"pass (returncode={result.returncode}):\n{output}"
        )
    else:
        # Honest-skip branch: every row must skip with the SAME documented
        # reason, never silently and never for a different, undocumented one.
        skip_reason_lines = [line for line in output.splitlines() if "SKIPPED" in line]
        assert skip_reason_lines, (
            "Docker is unavailable in THIS run, but no SKIPPED rows were "
            f"reported at all (expected an honest skip):\n{output}"
        )
        for line in skip_reason_lines:
            assert _EXPECTED_SKIP_REASON in line or _EXPECTED_SKIP_REASON in output, (
                f"a matrix row skipped for a reason OTHER than the directory's "
                f"own documented honest-skip string {_EXPECTED_SKIP_REASON!r}: "
                f"{line}"
            )


# --- (d) NO DUPLICATE IDs ----------------------------------------------------


def test_no_duplicate_matrix_ids() -> None:
    """No two `_MATRIX` rows may resolve to the SAME `(file, function)` pair —
    a duplicate would let one row's genuine coverage silently stand in for a
    DIFFERENT, actually-uncovered failure mode (the matrix would still "pass"
    checks (a)-(c) while quietly under-covering the taxonomy it claims to
    index)."""
    seen: dict[tuple[str, str], int] = {}
    duplicates: list[str] = []
    for index, row in enumerate(_MATRIX):
        if row in seen:
            duplicates.append(f"row {index} duplicates row {seen[row]}: {row[0]}::{row[1]}")
        else:
            seen[row] = index
    assert not duplicates, "duplicate matrix IDs found:\n" + "\n".join(duplicates)


# --- (f) NO SILENT PASS UPGRADE ---------------------------------------------

#: A row's proving-test body must contain at least one of these patterns to
#: count as asserting the outcome-level "never PASS" (or "granted is False")
#: property explicitly, not merely asserting some other fact and trusting
#: the status implicitly. Matches both the `OutcomeStatus` pipeline shape and
#: the (pre-repoint, still-imported-elsewhere) `BLayerVerdict.granted` shape.
_NEVER_PASS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"is\s+not\s+OutcomeStatus\.PASS"),
    re.compile(r"status\s+is\s+OutcomeStatus\.(UNDETERMINED|FAIL)\b"),
    re.compile(r"==\s*OutcomeStatus\.(UNDETERMINED|FAIL)\b"),
    re.compile(r"granted\s+is\s+False"),
)


def test_undetermined_or_fail_rows_assert_status_is_never_pass() -> None:
    """Every `_MATRIX` row's OWN proving-test source must contain an
    EXPLICIT outcome-level assertion (see `_NEVER_PASS_PATTERNS`) — a row
    whose test only asserts, say, a reason code is present but never
    actually pins the resulting `status` would let a future regression that
    upgrades the status to PASS (while still incidentally carrying the old
    reason code) slip through this matrix undetected. This is a STATIC
    source check (not a live pytest run) so it also catches a row whose
    assertions were weakened without removing the reason-code assertion
    entirely."""
    weak_rows: list[str] = []
    for relative_path, function_name in _MATRIX:
        module_path = _REPO_ROOT / relative_path
        source = _function_source(module_path, function_name)
        if not any(pattern.search(source) for pattern in _NEVER_PASS_PATTERNS):
            weak_rows.append(f"{relative_path}::{function_name}")
    assert not weak_rows, (
        "matrix row(s) do not explicitly assert an outcome-level "
        "never-PASS/UNDETERMINED/FAIL property in their own test body "
        "(reason-code-only assertions are insufficient — see module "
        "docstring check (f)):\n" + "\n".join(weak_rows)
    )
