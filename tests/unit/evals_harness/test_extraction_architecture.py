"""The extraction-architecture test (dependency-policy.md rule 12 / ADR-0002
rev.3): "추출 불변식: worker 분리 시 모듈 코드 변경 0 — evals/regression-suites
아키텍처 테스트로 검증."

Proves the worker-module boundary holds: every current worker-hosted
service package communicates with every OTHER service package ONLY via
published contracts (events/HTTP), never via a direct Python import — so
extracting any one of them to its own process/deployment requires ZERO
code change to any sibling service.

Three independent legs, deliberately NOT relying on a single mechanism:

  1. `test_declared_independence_set_matches_the_real_service_packages` —
     the `.importlinter` `services-are-independent` `type = independence`
     contract's own `modules` list is derived HERE from the actual
     `services/**/pyproject.toml` files on disk (via `tomllib`, stdlib) —
     catches a new service being added/renamed without also being
     registered in the independence contract (a silent regression risk the
     contract's mere EXISTENCE does not protect against).
  2. `test_import_linter_reports_the_independence_contract_kept` — runs the
     REAL `lint-imports` CLI (the actual enforcement mechanism CI relies
     on) as a subprocess against this repo's `.importlinter` and asserts
     the independence contract is reported `KEPT` (green NOW, not merely
     declared).
  3. `test_ast_no_service_to_service_imports` — an independent,
     differently-implemented proof of the SAME invariant: `ast`-parses
     every `services/**/src/**/*.py` file directly (no import-linter
     involvement at all) and asserts no service package's source ever
     imports another service package's top-level module name — belt-and-
     suspenders against a bug in import-linter's own resolution engine.
"""

from __future__ import annotations

import ast
import configparser
import subprocess
import sys
import tomllib
from pathlib import Path

from harness_paths import REPO_ROOT

SERVICES_DIR = REPO_ROOT / "services"
IMPORTLINTER_PATH = REPO_ROOT / ".importlinter"


def _kebab_to_snake_package_name(project_name: str) -> str:
    return project_name.replace("-", "_")


def _real_service_package_names() -> set[str]:
    """Derive the set of currently-implemented worker service package
    names DIRECTLY from `services/**/pyproject.toml` files on disk (never
    from `.importlinter` itself — that would make this check circular)."""
    names: set[str] = set()
    for pyproject_path in SERVICES_DIR.glob("*/*/pyproject.toml"):
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project_name = data["project"]["name"]
        names.add(_kebab_to_snake_package_name(project_name))
    return names


def _independence_contract_modules() -> set[str]:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_PATH, encoding="utf-8")
    section = parser["importlinter:contract:services-are-independent"]
    assert section["type"].strip() == "independence", (
        "services-are-independent contract must be type=independence "
        "(the extraction invariant's enforcement mechanism)"
    )
    return {line.strip() for line in section["modules"].strip().splitlines() if line.strip()}


def test_declared_independence_set_matches_the_real_service_packages() -> None:
    real_services = _real_service_package_names()
    declared = _independence_contract_modules()
    assert real_services == declared, (
        "services/**/pyproject.toml package set != .importlinter "
        "services-are-independent.modules — a service was added/renamed without updating the "
        f"extraction-invariant contract. real={sorted(real_services)!r} "
        f"declared={sorted(declared)!r}"
    )
    # Sanity floor: this must not vacuously pass on an empty set.
    assert len(real_services) >= 5


def test_import_linter_reports_the_independence_contract_kept() -> None:
    # `import-linter`'s own package cannot be run via `-m` (it has no
    # `__main__.py`) — invoke its installed console-script entrypoint,
    # resolved relative to the running interpreter (same venv `bin/` every
    # other `uv run <tool>` invocation in this repo resolves against).
    lint_imports_script = Path(sys.executable).parent / "lint-imports"
    assert lint_imports_script.is_file(), (
        f"lint-imports console script not found at {lint_imports_script} — is "
        "import-linter installed in this environment?"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-internal tool
        [str(lint_imports_script), "--config", str(IMPORTLINTER_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined_output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"lint-imports failed (returncode={result.returncode}):\n{combined_output}"
    )
    assert "services must not import each other" in combined_output
    assert "0 broken" in combined_output


def _iter_service_source_files() -> list[Path]:
    files: list[Path] = []
    for src_dir in SERVICES_DIR.glob("*/*/src"):
        files.extend(src_dir.rglob("*.py"))
    return sorted(files)


def _top_level_imported_modules(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_ast_no_service_to_service_imports() -> None:
    service_package_names = _real_service_package_names()
    violations: list[str] = []
    for source_path in _iter_service_source_files():
        # services/<domain>/<service-dir>/src/<owning_package>/...
        owning_package = source_path.relative_to(REPO_ROOT).parts[4]
        imported = _top_level_imported_modules(source_path)
        cross_service_imports = (imported & service_package_names) - {owning_package}
        if cross_service_imports:
            violations.append(
                f"{source_path.relative_to(REPO_ROOT)} (package {owning_package!r}) imports "
                f"sibling service package(s) {sorted(cross_service_imports)!r} directly"
            )
    assert not violations, (
        "worker-module extraction invariant violated — a service imports another service's "
        "code directly instead of communicating via published contracts (events/HTTP):\n"
        + "\n".join(violations)
    )
