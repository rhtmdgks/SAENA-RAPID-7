"""Confirms the saena-forge chart's `values.yaml` PASSES `forgectl
preflight` (Google flag off) and FAILS it (Google flag on) — the w2-23
task's named forgectl-integration proof, run as a pytest so it participates
in `just verify`'s unit lane rather than only a manual `helm
template`/`forgectl` shell invocation.
"""

from __future__ import annotations

import copy
from typing import Any

import yaml
from saena_forgectl.preflight import run_preflight


class TestChartValuesPassPreflightWithGoogleOff:
    def test_run_preflight_passes(self, chart_dir: Any) -> None:
        report = run_preflight(str(chart_dir / "values.yaml"))
        assert report.passed is True, [(c.name, c.detail) for c in report.checks if not c.passed]

    def test_all_six_checks_present_and_passed(self, chart_dir: Any) -> None:
        report = run_preflight(str(chart_dir / "values.yaml"))
        names = {c.name for c in report.checks}
        assert names == {
            "image_digest_signature",
            "engine_flags",
            "external_secrets",
            "network_policy",
            "service_account_permissions",
            "migrations_reversible",
        }
        assert all(c.passed for c in report.checks)


class TestChartValuesFailPreflightWithGoogleOn:
    def test_gemini_enabled_fails_preflight(
        self, chart_dir: Any, tmp_path: Any, values_data: dict[str, Any]
    ) -> None:
        mutated = copy.deepcopy(values_data)
        mutated["global"]["engineScope"]["gemini"] = True
        mutated_path = tmp_path / "values-google-on.yaml"
        with mutated_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(mutated, f)

        report = run_preflight(str(mutated_path))

        assert report.passed is False
        failed_names = {c.name for c in report.failed_checks}
        assert "engine_flags" in failed_names
        engine_check = next(c for c in report.checks if c.name == "engine_flags")
        assert "gemini" in engine_check.detail

    def test_only_engine_flags_check_fails_isolating_the_mutation(
        self, tmp_path: Any, values_data: dict[str, Any]
    ) -> None:
        """A single-field mutation (gemini: false -> true) should fail
        exactly the engine_flags check and no other — proves the other 5
        checks are not accidentally coupled to engineScope shape."""
        mutated = copy.deepcopy(values_data)
        mutated["global"]["engineScope"]["gemini"] = True
        mutated_path = tmp_path / "values-google-on.yaml"
        with mutated_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(mutated, f)

        report = run_preflight(str(mutated_path))
        failed_names = {c.name for c in report.failed_checks}
        assert failed_names == {"engine_flags"}
