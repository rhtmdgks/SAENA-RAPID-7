"""`saena_forgectl.preflight.run_preflight` — full-report integration tests
over the fixture set. Each `values-fail-*.yaml` fixture must fail *exactly*
the check it was constructed to violate (and only that check), and the
passing fixture must clear all six.
"""

from __future__ import annotations

import pytest
from conftest import fixture_path
from saena_forgectl.errors import ValuesFileError
from saena_forgectl.models import PreflightReport
from saena_forgectl.preflight import run_preflight


class TestPassingFixtureClearsAllChecks:
    def test_all_six_checks_pass(self) -> None:
        report = run_preflight(fixture_path("values-passing.yaml"))
        assert report.passed is True
        assert len(report.checks) == 6
        assert report.failed_checks == ()

    def test_check_names_match_spec_order(self) -> None:
        report = run_preflight(fixture_path("values-passing.yaml"))
        names = [check.name for check in report.checks]
        assert names == [
            "image_digest_signature",
            "engine_flags",
            "external_secrets",
            "network_policy",
            "service_account_permissions",
            "migrations_reversible",
        ]


@pytest.mark.parametrize(
    "fixture_name,expected_failed_check",
    [
        ("values-fail-google-flag.yaml", "engine_flags"),
        ("values-fail-plaintext-secret.yaml", "external_secrets"),
        ("values-fail-missing-digest.yaml", "image_digest_signature"),
        ("values-fail-no-network-policy.yaml", "network_policy"),
        ("values-fail-sa-cluster-admin.yaml", "service_account_permissions"),
        ("values-fail-irreversible-migration.yaml", "migrations_reversible"),
    ],
)
class TestEachFailFixtureFailsExactlyOneCheck:
    def test_report_not_passed(self, fixture_name: str, expected_failed_check: str) -> None:
        report = run_preflight(fixture_path(fixture_name))
        assert report.passed is False

    def test_names_the_specific_failed_check(
        self, fixture_name: str, expected_failed_check: str
    ) -> None:
        report = run_preflight(fixture_path(fixture_name))
        failed_names = {check.name for check in report.failed_checks}
        assert expected_failed_check in failed_names

    def test_only_the_targeted_check_fails(
        self, fixture_name: str, expected_failed_check: str
    ) -> None:
        report = run_preflight(fixture_path(fixture_name))
        failed_names = {check.name for check in report.failed_checks}
        assert failed_names == {expected_failed_check}, (
            f"{fixture_name} was expected to fail only {expected_failed_check!r} "
            f"but failed {failed_names!r} — fixture is not minimally-scoped"
        )


class TestMalformedValuesFilePropagates:
    def test_raises_values_file_error_not_generic_exception(self) -> None:
        with pytest.raises(ValuesFileError):
            run_preflight(fixture_path("values-malformed.yaml"))

    def test_invalid_syntax_raises_values_file_error(self) -> None:
        with pytest.raises(ValuesFileError):
            run_preflight(fixture_path("values-invalid-syntax.yaml"))


class TestPreflightReportToDict:
    def test_shape(self) -> None:
        report = run_preflight(fixture_path("values-passing.yaml"))
        payload = report.to_dict()
        assert set(payload.keys()) == {"passed", "checks", "failed_check_names"}
        assert payload["passed"] is True
        assert payload["failed_check_names"] == []
        assert len(payload["checks"]) == 6
        for check_payload in payload["checks"]:
            assert set(check_payload.keys()) == {"name", "passed", "detail", "context"}

    def test_failing_report_lists_failed_names(self) -> None:
        report = run_preflight(fixture_path("values-fail-google-flag.yaml"))
        payload = report.to_dict()
        assert payload["passed"] is False
        assert "engine_flags" in payload["failed_check_names"]


class TestPreflightReportPassedProperty:
    def test_empty_checks_is_not_passed(self) -> None:
        """Vacuous-empty fails closed rather than silently reporting success."""
        report = PreflightReport(checks=())
        assert report.passed is False
