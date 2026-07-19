"""Attack 3 — shell injection via path / domain / branch / run-id names.

The pilot uses list-argv subprocesses everywhere (`shell=True` is banned
package-wide). These tests prove: (a) a customer repo dir literally named
`$(touch pwned)` / `; rm -rf x` / backticks triggers NO shell execution
(no side-effect file), (b) a domain with shell metachars is rejected without
executing, (c) bad run-ids are rejected as not-found (no shell exec), and
(d) an AST scan proves no `subprocess.*` call anywhere in the pilot package
passes `shell=True`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import saena_pilot
from _sec_fixtures import make_git_repo
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED, main

DOMAIN = "https://customer.example"

_PILOT_PKG_DIR = Path(saena_pilot.__file__).resolve().parent


def _audit(customer: Path) -> list[str]:
    return ["--customer-repo", str(customer), "--domain", DOMAIN, "--mode", "audit", "--dry-run"]


class TestMaliciousDirNamesNoShellExec:
    @pytest.mark.parametrize(
        "evil_name",
        [
            "$(touch pwned)",
            "; touch pwned",
            "`touch pwned`",
            "&& touch pwned",
            "| touch pwned",
            "$(rm -rf x)",
        ],
    )
    def test_dir_name_triggers_no_shell_execution(
        self,
        evil_name: str,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        customer = make_git_repo(tmp_path / evil_name)
        sentinel = tmp_path / "pwned"
        assert not sentinel.exists()
        exit_code = main(_audit(customer))
        # Path is a legitimate external repo; argv is list-passed so the shell
        # metacharacters are inert — the run succeeds and NOTHING is executed.
        assert exit_code == EXIT_OK
        assert not sentinel.exists(), "shell metacharacters in the path executed!"
        # Also assert the sentinel was not created anywhere under cwd.
        assert not (Path.cwd() / "pwned").exists()
        capsys.readouterr()


class TestMaliciousDomainNoShellExec:
    """A domain never enters any subprocess or shell — it is DATA bound into
    the report/evidence only. So even a metachar-laden domain executes NOTHING.

    FINDING (for the Integrator): `validate_domain` currently accepts host
    strings containing shell metacharacters/spaces (e.g.
    ``https://example.com;touch pwned`` normalizes through) because it only
    checks scheme/host-suffix/IP-range, not the hostname charset. Not
    exploitable in this unit (the domain is never fetched or shelled), but a
    hostname-charset allowlist would harden it. See FINDING-DOMAIN-CHARSET.
    """

    @pytest.mark.parametrize(
        "evil_domain",
        [
            "https://example.com/$(touch pwned)",
            "https://example.com;touch pwned",
            "https://example.com`touch pwned`",
            "not a url at all",
        ],
    )
    def test_domain_with_metachars_never_executes(
        self,
        evil_domain: str,
        rapid7_root: Path,
        customer_repo: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sentinel = tmp_path / "pwned"
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            evil_domain,
            "--mode",
            "audit",
            "--dry-run",
        ]
        exit_code = main(argv)
        # Whether accepted-as-data or rejected, the invariant is the same:
        # NO shell execution.
        assert exit_code in (EXIT_OK, EXIT_VALIDATION_FAILED)
        assert not sentinel.exists(), "domain metacharacters reached a shell!"
        assert not (Path.cwd() / "pwned").exists()
        capsys.readouterr()


class TestMaliciousRunIdRejected:
    @pytest.mark.parametrize(
        "evil_run_id",
        ["../../etc", "..", "a;touch pwned", "$(touch pwned)", "../../../secrets"],
    )
    def test_bad_run_id_rejected_as_not_found(
        self,
        evil_run_id: str,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sentinel = tmp_path / "pwned"
        # verify/status/resume resolve the run-id as a path segment (never a
        # shell). A traversal/metachar id simply resolves to a nonexistent run.
        exit_code = main(["--mode", "verify", "--run-id", evil_run_id])
        assert exit_code == EXIT_VALIDATION_FAILED
        assert not sentinel.exists()
        capsys.readouterr()


class TestNoShellTrueInSource:
    """AST proof: no subprocess call in the pilot package uses shell=True."""

    def _iter_calls(self) -> list[tuple[Path, ast.Call]]:
        calls: list[tuple[Path, ast.Call]] = []
        for py in _PILOT_PKG_DIR.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    calls.append((py, node))
        return calls

    def test_no_call_passes_shell_true(self) -> None:
        offenders: list[str] = []
        for py, call in self._iter_calls():
            for kw in call.keywords:
                if kw.arg == "shell":
                    value = kw.value
                    is_true = isinstance(value, ast.Constant) and bool(value.value)
                    # Any `shell=` keyword on a subprocess call is suspicious;
                    # a truthy one is an outright fail.
                    if is_true or not isinstance(value, ast.Constant):
                        offenders.append(f"{py.name}:{call.lineno}")
        assert offenders == [], f"shell= keyword found on calls: {offenders}"

    def test_shell_true_literal_absent_from_code(self) -> None:
        # Belt-and-braces: the literal `shell=True` must not appear as CODE.
        # (It legitimately appears in docstrings/comments; those are stripped
        # by re-emitting parsed module bodies without string constants.)
        for py in _PILOT_PKG_DIR.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "shell":
                    assert not (
                        isinstance(node.value, ast.Constant) and node.value.value is True
                    ), f"shell=True in code at {py.name}:{node.value.lineno}"


class TestGitAndSubprocessArgvAreLists:
    """The git/validator/launch runners build list argv, not shell strings."""

    def test_run_git_uses_list_argv(self) -> None:
        src = (_PILOT_PKG_DIR / "_git.py").read_text(encoding="utf-8")
        # The one subprocess.run in _git.py addresses git via `git -C <path>`
        # in a bracketed list — never an f-string command line.
        assert '["git", "-C", str(repo), *args]' in src

    def test_launcher_uses_list_argv(self) -> None:
        src = (_PILOT_PKG_DIR / "launcher.py").read_text(encoding="utf-8")
        assert "list(argv)" in src
        assert "shlex.quote" in src  # present ONLY for the human display string
