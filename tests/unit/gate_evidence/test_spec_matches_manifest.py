"""Drift guard: the evidence-validator SSOT (``tools/validation/
gate_evidence_spec.py``) must equal the live required-scenario manifests
(``tests/integration/_measurement_e2e_completeness.py`` +
``_failure_completeness.py``). The strict renderer pins absolute counts (28, 31,
16, 15, per-leg) so a self-consistent-but-wrong evidence payload cannot pass;
this test proves those absolutes are not stale magic numbers but track the
manifests — if a required scenario is added/removed, this fails loudly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (
    _REPO_ROOT / "tools" / "validation",
    _REPO_ROOT / "tests" / "integration",
    _REPO_ROOT / "tests" / "integration" / "measurement_failure",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _failure_completeness as fail_manifest  # noqa: E402
import _measurement_e2e_completeness as e2e_manifest  # noqa: E402
from gate_evidence_spec import SPEC  # noqa: E402


def test_e2e_spec_matches_manifest() -> None:
    spec = SPEC["e2e"]
    scenarios = e2e_manifest.REQUIRED_SCENARIOS
    assert spec.expected_count == len(scenarios) == 28, (
        f"e2e expected_count {spec.expected_count} != manifest {len(scenarios)}"
    )
    # Per-leg expected == number of manifest scenarios tagged with that leg.
    for leg, expected in spec.leg_expected.items():
        actual = sum(1 for s in scenarios if leg in s.legs)
        assert actual == expected, f"e2e leg '{leg}': spec {expected} != manifest {actual}"
    # Required witness legs are real backend legs present in the manifest.
    manifest_legs = {leg for s in scenarios for leg in s.legs}
    for leg in spec.required_witness_legs:
        assert leg in manifest_legs, f"e2e required witness leg '{leg}' absent from manifest"


def test_failure_spec_matches_manifest() -> None:
    spec = SPEC["failure-modes"]
    scenarios = fail_manifest.REQUIRED_SCENARIOS
    assert spec.expected_count == len(scenarios) == 31
    primary = sum(1 for s in scenarios if s.category == fail_manifest.CATEGORY_PRIMARY)
    recovery = sum(1 for s in scenarios if s.category == fail_manifest.CATEGORY_RECOVERY)
    assert spec.primary_expected == primary == 16, (
        f"primary spec {spec.primary_expected} != {primary}"
    )
    assert spec.recovery_expected == recovery == 15, (
        f"recovery spec {spec.recovery_expected} != {recovery}"
    )
    assert spec.primary_expected + spec.recovery_expected == spec.expected_count
    assert spec.postgres_scenarios == len(scenarios) == 31
    assert spec.leg_expected["postgres"] == len(scenarios)


def test_authorized_unexpected_files_exist() -> None:
    for gate_spec in SPEC.values():
        for rel in gate_spec.authorized_unexpected_files:
            assert (_REPO_ROOT / rel).is_file(), f"authorized guard file missing: {rel}"
