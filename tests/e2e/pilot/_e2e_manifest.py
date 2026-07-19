"""Authoritative manifest SSOT + completeness evaluation for the REQUIRED pilot
E2E lane (w6-14, mission W6-26).

Why this exists
---------------
The Wave-5 required-mode guards close *zero-collected / all-skipped* fail-open,
but a caller who selects a *subset* (``-k nextjs-audit``) leaves the selected
set fully passing, so the lane went GREEN having run only a fraction of the
required scenarios — a partial-selection fail-open. The fix (mirrored from
``tests/integration/_measurement_e2e_completeness.py``) is an authoritative
manifest of every required E2E *scenario* compared against what actually
EXECUTED and PASSED. Any required scenario that was deselected, never collected,
skipped, or did not pass is a HARD FAILURE — the guard knows the *expected* set
independently of the *selected* set, so a selection option cannot shrink it.

Association mechanism
---------------------
Each required scenario has a stable ``scenario_id`` and a filesystem-safe
``key``. Every scenario *test function* is named ``test_{key}__{detail}`` and
lives in one of the SCENARIO modules (NOT the excluded meta module). A
collected non-meta test is mapped to its scenario by longest-``key`` prefix
match; the keys are mutually non-prefixing, so the mapping is unambiguous. A
drift meta-test (in the excluded module) asserts, via an independent
``--collect-only`` subprocess, that the set of scenarios present in the suite
equals ``EXPECTED_SCENARIO_IDS`` in BOTH directions and that no collected
non-meta test is an *orphan* (matches no scenario key). So a renamed/removed
scenario, a new scenario absent from the manifest, or a mistyped test name all
fail loudly.

TEST-SUPPORT ONLY — never imported by any production/runtime package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: The required-mode arming env var. Fail-SAFE: any value other than
#: ""/0/false/no/off arms (a caller who set it at all meant the required lane).
REQUIRED_ENV_VAR = "SAENA_PILOT_E2E_REQUIRED"

#: Optional dump target: when set, ``conftest.pytest_collection_finish`` writes
#: the full collected node-id list (unarmed) so the drift meta-test can read an
#: authoritative, selection-independent collection.
DUMP_ENV_VAR = "SAENA_PILOT_E2E_DUMP"

#: Exit code for a required-lane HARD FAILURE (non-zero, non-5; the Wave-5
#: convention for "false-green upgraded to red").
HARD_FAIL_EXIT = 6

#: Test module basenames that are META (guard self-tests + drift meta-test):
#: container-free-equivalent, they must run on every host and are NOT scenario
#: tests, so they are excluded from the required-scenario accounting.
META_MODULES: frozenset[str] = frozenset({"test_completeness_guard.py"})

_THIS_DIR = Path(__file__).resolve().parent
# repo root is …/tests/e2e/pilot -> parents[2]
_REPO_ROOT = _THIS_DIR.parents[2]


@dataclass(frozen=True)
class RequiredScenario:
    """One required E2E scenario. ``scenario_id`` is the stable semantic name;
    ``key`` is the function-name prefix its tests carry (``test_{key}__…``);
    ``description`` documents what the scenario proves end to end."""

    scenario_id: str
    key: str
    description: str


# --------------------------------------------------------------------------- #
# THE MANIFEST. Every required pilot-E2E scenario. Adding/removing/renaming a
# scenario REQUIRES a matching edit here — the drift meta-test enforces the
# equality (both directions) against the actual collected suite.
# --------------------------------------------------------------------------- #
REQUIRED_SCENARIOS: tuple[RequiredScenario, ...] = (
    RequiredScenario(
        "nextjs-audit",
        "nextjs_audit",
        "Audit a Next.js customer site end to end: framework detected SUPPORTED, "
        "test command reported verbatim, launch attaches the customer root read-only.",
    ),
    RequiredScenario(
        "static-audit",
        "static_audit",
        "Audit a static-HTML customer site (no package.json): SUPPORTED static-html, "
        "no writes to the customer tree.",
    ),
    RequiredScenario(
        "dirty-blocks-implement",
        "dirty_blocks_implement",
        "A dirty customer tree BLOCKS implement (fail-closed) while only WARNing in "
        "read modes; the pre-existing uncommitted work is never touched.",
    ),
    RequiredScenario(
        "unicode-path-audit",
        "unicode_path_audit",
        "A customer path containing spaces AND non-ASCII segments audits cleanly and "
        "survives verbatim through boundary resolution and the launch argv.",
    ),
    RequiredScenario(
        "malicious-quarantined",
        "malicious_quarantined",
        "A hostile CLAUDE.md prompt injection is treated as DATA (hashed, never "
        "followed) and a planted secret-shaped sentinel never reaches any artifact "
        "(guard fails closed when it would).",
    ),
    RequiredScenario(
        "unsupported-reportonly",
        "unsupported_reportonly",
        "A WordPress/PHP customer repo is classified UNSUPPORTED report-only; the run "
        "still completes read-only with zero writes.",
    ),
    RequiredScenario(
        "docker-absent-honest",
        "docker_absent_honest",
        "With no docker binary on PATH the preflight reports Docker absent honestly and "
        "the (container-free) lane still runs.",
    ),
    RequiredScenario(
        "interrupt-resume",
        "interrupt_resume",
        "A started run is 'interrupted' then resumed by run-id: status/verify reflect "
        "prior state; resume is refused after a customer/RAPID-7 SHA change.",
    ),
    RequiredScenario(
        "no-copy-invariant",
        "no_copy_invariant",
        "After a full lifecycle RAPID-7 stays clean, the customer repo is never copied "
        "into RAPID-7, and run metadata lives only under SAENA_PILOT_HOME.",
    ),
    RequiredScenario(
        "implement-worktree-isolation",
        "implement_worktree_isolation",
        "implement writes ONLY inside the dedicated saena-pilot/<run-id> worktree/branch "
        "outside both repos; the customer root stays clean; the launch attaches the "
        "worktree, not the root.",
    ),
    RequiredScenario(
        "evidence-integrity",
        "evidence_integrity",
        "The evidence chain verifies, records the real lifecycle events in order and "
        "binds the skill bundle; any tamper is detected.",
    ),
    RequiredScenario(
        "bundle-fail-closed",
        "bundle_fail_closed",
        "A missing/invalid skill bundle makes the pilot refuse to start "
        "(EXIT_BUNDLE_INVALID) with no bypass.",
    ),
)

EXPECTED_SCENARIO_IDS: frozenset[str] = frozenset(s.scenario_id for s in REQUIRED_SCENARIOS)
_KEYS_BY_ID: dict[str, str] = {s.scenario_id: s.key for s in REQUIRED_SCENARIOS}
# Longest key first so prefix matching is deterministic (keys are mutually
# non-prefixing, but sort defensively).
_KEYS_SORTED: tuple[tuple[str, str], ...] = tuple(
    sorted(((s.key, s.scenario_id) for s in REQUIRED_SCENARIOS), key=lambda kv: -len(kv[0]))
)


def required_armed() -> bool:
    """Fail-SAFE arming: any non-empty value other than an explicit disable
    (``0``/``false``/``no``/``off``) arms required mode."""
    raw = os.environ.get(REQUIRED_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def module_basename(node_id: str) -> str:
    """The test module basename of a pytest node id (``path::func`` → ``path``
    basename)."""
    path_part = node_id.partition("::")[0]
    return Path(path_part).name


def is_meta_node(node_id: str) -> bool:
    return module_basename(node_id) in META_MODULES


def _func_name(node_id: str) -> str:
    """The final ``::``-separated component (the test function name)."""
    return node_id.split("::")[-1]


def scenario_for_node(node_id: str) -> str | None:
    """Map a collected NON-meta node id to its scenario_id by ``test_{key}__``
    prefix, or None if it matches no scenario (an orphan) or is a meta node."""
    if is_meta_node(node_id):
        return None
    func = _func_name(node_id)
    for key, scenario_id in _KEYS_SORTED:
        if func.startswith(f"test_{key}__") or func == f"test_{key}":
            return scenario_id
    return None


@dataclass
class CompletenessReport:
    expected: frozenset[str]
    satisfied: frozenset[str]  # scenarios with >=1 pass and no non-pass
    skipped_scenarios: frozenset[str]
    failed_scenarios: frozenset[str]
    missing_scenarios: frozenset[str]  # zero collected tests
    orphans: frozenset[str]  # collected non-meta node ids matching no scenario
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return not self.reasons


def evaluate(
    *,
    collected: set[str],
    passed: set[str],
    skipped: set[str],
    failed: set[str],
) -> CompletenessReport:
    """Compare the manifest against the actual collected/passed/skipped/failed
    node sets. A scenario is SATISFIED iff it has >=1 collected test, >=1 of its
    tests passed, and NONE of its tests were skipped or failed. Any required
    scenario not satisfied — and any orphan test — yields a reason (HARD FAIL)."""
    per_scenario_collected: dict[str, set[str]] = {sid: set() for sid in EXPECTED_SCENARIO_IDS}
    orphans: set[str] = set()
    for node in collected:
        if is_meta_node(node):
            continue
        sid = scenario_for_node(node)
        if sid is None:
            orphans.add(node)
        else:
            per_scenario_collected[sid].add(node)

    satisfied: set[str] = set()
    skipped_scenarios: set[str] = set()
    failed_scenarios: set[str] = set()
    missing_scenarios: set[str] = set()
    for sid, nodes in per_scenario_collected.items():
        if not nodes:
            missing_scenarios.add(sid)
            continue
        if nodes & failed:
            failed_scenarios.add(sid)
        if nodes & skipped:
            skipped_scenarios.add(sid)
        if (nodes & passed) and not (nodes & failed) and not (nodes & skipped):
            satisfied.add(sid)

    reasons: list[str] = []
    if not EXPECTED_SCENARIO_IDS:
        reasons.append("required E2E scenario manifest is EMPTY (SSOT lost)")
    unsatisfied = EXPECTED_SCENARIO_IDS - satisfied
    if unsatisfied:
        sample = ", ".join(sorted(unsatisfied))
        reasons.append(
            f"{len(unsatisfied)} of {len(EXPECTED_SCENARIO_IDS)} REQUIRED E2E scenario(s) "
            f"did not execute-and-PASS (deselected / not collected / skipped / failed): {sample}"
        )
    if orphans:
        reasons.append(
            f"{len(orphans)} collected non-meta test(s) match no manifest scenario (orphans): "
            + ", ".join(sorted(orphans)[:6])
        )
    return CompletenessReport(
        expected=EXPECTED_SCENARIO_IDS,
        satisfied=frozenset(satisfied),
        skipped_scenarios=frozenset(skipped_scenarios),
        failed_scenarios=frozenset(failed_scenarios),
        missing_scenarios=frozenset(missing_scenarios),
        orphans=frozenset(orphans),
        reasons=reasons,
    )


def format_failure(report: CompletenessReport) -> str:
    sep = "\n  - "
    return (
        f"\n{REQUIRED_ENV_VAR} HARD FAILURE (exit {HARD_FAIL_EXIT}) — "
        f"required-scenario completeness:{sep}"
        + sep.join(report.reasons)
        + f"\n  expected={len(report.expected)} satisfied={len(report.satisfied)} "
        f"missing={len(report.missing_scenarios)} skipped={len(report.skipped_scenarios)} "
        f"failed={len(report.failed_scenarios)} orphans={len(report.orphans)}"
        "\n  A required pilot-E2E run must execute-and-PASS EVERY manifest scenario — a "
        "partial -k/-m/--deselect/single-node/PYTEST_ADDOPTS selection can never make it "
        f"green. Run the full lane, or invoke without {REQUIRED_ENV_VAR} for the local lane."
    )
