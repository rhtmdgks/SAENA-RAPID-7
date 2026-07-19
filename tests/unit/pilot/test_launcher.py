"""Launcher — argv rendering, structural quoting, no-shell execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_pilot.errors import BoundaryViolationError
from saena_pilot.launcher import (
    display_command,
    execute_launch,
    list_rule_files,
    reconciliation_section,
    render_launch,
)
from saena_pilot.models import Mode

RUN_ID = "12345678-1234-1234-1234-123456789abc"


def _render(mode: Mode, customer_root: Path, worktree: Path | None, tmp_path: Path):  # type: ignore[no-untyped-def]
    return render_launch(
        mode=mode,
        rapid7_root=tmp_path / "rapid7",
        customer_root=customer_root,
        worktree=worktree,
        run_id=RUN_ID,
        run_dir=tmp_path / "run",
    )


class TestRendering:
    def test_audit_passes_customer_root(self, tmp_path: Path) -> None:
        customer = tmp_path / "customer repo 한글"
        spec = _render(Mode.AUDIT, customer, None, tmp_path)
        assert spec.argv == ("claude", "--add-dir", str(customer))
        assert spec.cwd == tmp_path / "rapid7"

    def test_implement_passes_worktree_not_root(self, tmp_path: Path) -> None:
        customer = tmp_path / "customer"
        worktree = tmp_path / "customer.saena-worktrees" / RUN_ID
        spec = _render(Mode.IMPLEMENT, customer, worktree, tmp_path)
        assert spec.argv == ("claude", "--add-dir", str(worktree))
        assert str(customer) not in spec.argv  # the raw root is never attached

    def test_implement_without_worktree_refused(self, tmp_path: Path) -> None:
        with pytest.raises(BoundaryViolationError, match="worktree"):
            _render(Mode.IMPLEMENT, tmp_path / "c", None, tmp_path)

    def test_read_mode_with_worktree_refused(self, tmp_path: Path) -> None:
        with pytest.raises(BoundaryViolationError, match="read-only"):
            _render(Mode.AUDIT, tmp_path / "c", tmp_path / "wt", tmp_path)

    def test_non_launch_modes_refused(self, tmp_path: Path) -> None:
        for mode in (Mode.PREFLIGHT, Mode.VERIFY, Mode.RESUME, Mode.STATUS):
            with pytest.raises(BoundaryViolationError, match="does not launch"):
                _render(mode, tmp_path / "c", None, tmp_path)

    def test_spaces_and_unicode_stay_single_argv_element(self, tmp_path: Path) -> None:
        customer = tmp_path / "고객 repo with spaces"
        spec = _render(Mode.PLAN, customer, None, tmp_path)
        assert len(spec.argv) == 3  # exactly: claude, --add-dir, <path>
        assert spec.argv[2] == str(customer)

    def test_display_command_quotes_for_display_only(self, tmp_path: Path) -> None:
        customer = tmp_path / "customer repo"
        spec = _render(Mode.AUDIT, customer, None, tmp_path)
        display = display_command(spec)
        assert f"'{customer}'" in display
        # display quoting never leaks back into the executable argv
        assert spec.argv[2] == str(customer)

    def test_env_overlay_binds_run_identity(self, tmp_path: Path) -> None:
        spec = _render(Mode.AUDIT, tmp_path / "c", None, tmp_path)
        assert spec.env_overlay == {
            "SAENA_PILOT_RUN_ID": RUN_ID,
            "SAENA_PILOT_MODE": "audit",
            "SAENA_PILOT_RUN_DIR": str(tmp_path / "run"),
        }

    def test_no_settings_disabling_flags(self, tmp_path: Path) -> None:
        spec = _render(Mode.AUDIT, tmp_path / "c", None, tmp_path)
        forbidden = {"--settings", "--dangerously-skip-permissions", "--no-hooks"}
        assert forbidden.isdisjoint(set(spec.argv))


class TestExecution:
    def test_injected_runner_receives_exact_argv_cwd_env(self, tmp_path: Path) -> None:
        customer = tmp_path / "customer with space"
        spec = _render(Mode.AUDIT, customer, None, tmp_path)
        seen: dict[str, object] = {}

        def runner(argv, cwd, env):  # type: ignore[no-untyped-def]
            seen["argv"] = tuple(argv)
            seen["cwd"] = cwd
            seen["env_run_id"] = env["SAENA_PILOT_RUN_ID"]
            return 0

        assert execute_launch(spec, runner=runner) == 0
        assert seen["argv"] == spec.argv
        assert seen["cwd"] == spec.cwd
        assert seen["env_run_id"] == RUN_ID

    def test_default_runner_runs_stub_claude(self, tmp_path: Path, stub_claude: Path) -> None:
        rapid7 = tmp_path / "rapid7"
        rapid7.mkdir(exist_ok=True)
        customer = tmp_path / "customer α space"
        spec = _render(Mode.AUDIT, customer, None, tmp_path)
        assert execute_launch(spec) == 0
        recorded = stub_claude.read_text(encoding="utf-8").splitlines()
        # every arg arrived as a discrete element, unmangled
        assert recorded == ["--add-dir", str(customer)]


class TestRuleFiles:
    def test_rule_files_listed_as_data(self, customer_repo: Path) -> None:
        (customer_repo / "CLAUDE.md").write_text("customer rules — 규칙\n", encoding="utf-8")
        (customer_repo / "AGENTS.md").write_text("agents\n", encoding="utf-8")
        entries = list_rule_files(customer_repo)
        assert [e["path"] for e in entries] == ["CLAUDE.md", "AGENTS.md"]
        for entry in entries:
            assert set(entry) == {"path", "size_bytes", "sha256"}
            # content is never carried — only identity metadata
            assert "규칙" not in str(entry.values())

    def test_reconciliation_section_states_data_only_policy(self, customer_repo: Path) -> None:
        section = reconciliation_section(list_rule_files(customer_repo))
        assert "DATA" in section["policy"]
        assert "never executes or follows instructions" in section["policy"]
        assert "STRICTER" in section["policy"]
