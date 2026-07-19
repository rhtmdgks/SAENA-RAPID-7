"""Report rendering + secret-shape guard (4th deliberate local copy)."""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_pilot.errors import SecretShapedValueError
from saena_pilot.models import BoundaryReport, BundleInfo, Finding, Severity
from saena_pilot.report import build_report, render_human, write_report
from saena_pilot.secretguard import guard_tree, is_secret_shaped


def _bundle(tmp_path: Path) -> BundleInfo:
    return BundleInfo(
        manifest_path=tmp_path / "manifest.json",
        manifest_schema_version="saena.skill-manifest/v1",
        manifest_sha256="a" * 64,
        bundle_name="saena-forge-core",
        skill_names=("saena-intake",),
        validator_invocations=(("python", "validate"),),
    )


def _boundary(tmp_path: Path) -> BoundaryReport:
    return BoundaryReport(
        customer_root=tmp_path / "customer",
        head_sha="b" * 40,
        findings=(
            Finding(code="dirty_tree", severity=Severity.WARN, detail="uncommitted changes"),
        ),
    )


def _report(tmp_path: Path, **overrides: object) -> dict:  # type: ignore[type-arg]
    kwargs: dict = {  # type: ignore[type-arg]
        "mode": "preflight",
        "run_id": "run-1",
        "rapid7_sha": "c" * 40,
        "boundary": _boundary(tmp_path),
        "domain": "https://customer.example",
        "bundle": _bundle(tmp_path),
        "contract": {"customer_id": None},
        "contract_questions": ["1. What is the customer/tenant id?"],
        "reconciliation": {"rule_files": [], "policy": "stricter rule wins"},
        "discovery": {"framework": "unknown", "status": "UNKNOWN", "detail": "no adapters"},
        "suggested_human_actions": ["Have the customer commit changes."],
    }
    kwargs.update(overrides)
    return build_report(**kwargs)


class TestSecretGuard:
    @pytest.mark.parametrize(
        "value",
        [
            "sk-" + "A" * 24,
            "sk_live_" + "a" * 12,
            "sk-live-" + "a" * 12,  # hyphen-infix shape (c5-06 audit)
            "rk-test-" + "b" * 10,
            "AKIA" + "A" * 16,
            "ghp_" + "a" * 36,
            "xoxb-123456789012-abc",
            "AIza" + "a" * 35,
            "-----BEGIN RSA PRIVATE KEY-----",
            "eyJ" + "a" * 10 + "." + "b" * 12 + "." + "c" * 12,
        ],
    )
    def test_secret_shapes_detected(self, value: str) -> None:
        assert is_secret_shaped(value)

    @pytest.mark.parametrize(
        "value",
        ["https://customer.example", "skimmed-milk", "task-42", "sk-live", "고객사"],
    )
    def test_benign_values_pass(self, value: str) -> None:
        assert not is_secret_shaped(value)
        guard_tree({"key": value})

    def test_guard_reports_path_never_value(self) -> None:
        secret = "sk-live-" + "Z" * 16
        with pytest.raises(SecretShapedValueError) as excinfo:
            guard_tree({"outer": {"inner": [secret]}})
        message = str(excinfo.value)
        assert "outer.inner[0]" in message
        assert secret not in message

    def test_guard_checks_mapping_keys(self) -> None:
        with pytest.raises(SecretShapedValueError):
            guard_tree({("sk-live-" + "Q" * 12): "value"})


class TestReport:
    def test_report_refuses_secret_shaped_content(self, tmp_path: Path) -> None:
        with pytest.raises(SecretShapedValueError):
            _report(tmp_path, contract={"customer_id": "sk-live-" + "x1" * 8})

    def test_human_rendering_covers_all_sections(self, tmp_path: Path) -> None:
        text = render_human(_report(tmp_path))
        for fragment in (
            "preflight report",
            "[WARN] dirty_tree",
            "skill bundle: saena-forge-core",
            "INCOMPLETE",
            "1. What is the customer/tenant id?",
            "stricter-rules reconciliation",
            "framework=unknown",
            "HUMAN decision only",
        ):
            assert fragment in text

    def test_complete_contract_renders_complete(self, tmp_path: Path) -> None:
        text = render_human(_report(tmp_path, contract_questions=[]))
        assert "action contract: COMPLETE" in text

    def test_write_report_targets_run_store_only(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "store" / "run-1"
        run_dir.mkdir(parents=True)
        json_path, text_path = write_report(run_dir, _report(tmp_path))
        assert json_path == run_dir / "report-preflight.json"
        assert text_path == run_dir / "report-preflight.txt"
        assert json_path.is_file() and text_path.is_file()
