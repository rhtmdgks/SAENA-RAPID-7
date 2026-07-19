"""End-to-end CLI wiring: `saena-pilot --mode audit --dry-run` on a Next.js
fixture repo reports framework=nextjs plus an honest docker section, and the
planted `.env` secret never reaches any pilot artifact."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from _discovery_fixtures import (
    PLANTED_ENV_SECRET,
    commit_all,
    make_docker_shim,
    make_nextjs_repo,
    run_git,
)
from saena_pilot.cli import EXIT_OK, main

DOMAIN = "https://customer.example"


@pytest.fixture
def nextjs_customer_repo(tmp_path: Path) -> Path:
    root = tmp_path / "customer next 저장소"
    make_nextjs_repo(root)
    (root / ".env").write_text(f"API_KEY={PLANTED_ENV_SECRET}\n", encoding="utf-8")
    assert run_git(root, "init", "-q", "-b", "main").returncode == 0
    commit_all(root)
    return root


@pytest.fixture
def healthy_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "docker-shim-bin"
    make_docker_shim(bin_dir, "healthy")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _audit_dry_run(customer_repo: Path) -> tuple[int, dict]:  # type: ignore[type-arg]
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = main(
            [
                "--customer-repo",
                str(customer_repo),
                "--domain",
                DOMAIN,
                "--mode",
                "audit",
                "--dry-run",
                "--json",
            ]
        )
    return exit_code, json.loads(buffer.getvalue())


def test_audit_report_shows_nextjs_and_docker_sections(
    rapid7_root: Path, pilot_home: Path, nextjs_customer_repo: Path, healthy_docker: None
) -> None:
    exit_code, payload = _audit_dry_run(nextjs_customer_repo)
    assert exit_code == EXIT_OK
    discovery = payload["report"]["discovery"]
    assert discovery["framework"] == "nextjs"
    assert discovery["status"] == "SUPPORTED"
    assert discovery["build_command"] == "next build"
    assert discovery["routes"]  # inventory made it into the report
    docker = payload["report"]["docker"]
    assert docker["cli_present"] is True
    assert docker["daemon_healthy"] is True
    assert docker["server_version"] == "28.1.1"


def test_human_report_text_renders_framework_and_docker(
    rapid7_root: Path, pilot_home: Path, nextjs_customer_repo: Path, healthy_docker: None
) -> None:
    exit_code, payload = _audit_dry_run(nextjs_customer_repo)
    assert exit_code == EXIT_OK
    text_path = next(path for path in payload["report_paths"] if path.endswith(".txt"))
    text = Path(text_path).read_text(encoding="utf-8")
    assert "framework=nextjs" in text
    assert "docker: cli_present=True daemon_healthy=True" in text


def test_env_secret_never_reaches_any_pilot_artifact(
    rapid7_root: Path, pilot_home: Path, nextjs_customer_repo: Path, healthy_docker: None
) -> None:
    exit_code, payload = _audit_dry_run(nextjs_customer_repo)
    assert exit_code == EXIT_OK
    assert PLANTED_ENV_SECRET not in json.dumps(payload, ensure_ascii=False)
    run_dir = Path(payload["report_paths"][0]).parent
    for artifact in sorted(run_dir.rglob("*")):
        if artifact.is_file():
            assert PLANTED_ENV_SECRET not in artifact.read_text(encoding="utf-8", errors="replace")
    # …but the .env file itself IS flagged by name.
    assert ".env" in payload["report"]["discovery"]["env_files"]


def test_docker_absence_reported_honestly_in_report(
    rapid7_root: Path,
    pilot_home: Path,
    nextjs_customer_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PATH without docker, but git must stay reachable for the pilot itself.
    bare = tmp_path / "bare-bin"
    bare.mkdir()
    for tool in ("git", "sh"):
        source = None
        for candidate in ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin"):
            if (Path(candidate) / tool).is_file():
                source = Path(candidate) / tool
                break
        assert source is not None
        os.symlink(source, bare / tool)
    monkeypatch.setenv("PATH", str(bare))
    exit_code, payload = _audit_dry_run(nextjs_customer_repo)
    assert exit_code == EXIT_OK  # audit is container-free — absence never blocks
    docker = payload["report"]["docker"]
    assert docker["cli_present"] is False
    assert docker["daemon_healthy"] is False
    assert docker["container_verification_available"] is False


def test_plain_repo_still_reports_unknown_through_real_adapters(
    rapid7_root: Path, pilot_home: Path, tmp_path: Path, healthy_docker: None
) -> None:
    root = tmp_path / "plain-customer"
    root.mkdir()
    (root / "README.md").write_text("plain\n", encoding="utf-8")
    assert run_git(root, "init", "-q", "-b", "main").returncode == 0
    commit_all(root)
    exit_code, payload = _audit_dry_run(root)
    assert exit_code == EXIT_OK
    discovery = payload["report"]["discovery"]
    assert discovery["framework"] == "unknown"
    assert discovery["status"] == "UNKNOWN"
    assert "not guessed" in discovery["detail"]
