"""N-1 git-tag compatibility harness (ADR-0012, tests/contract/README.md
"Compatibility harness").

For each `packages/contracts/registry.json` entry:
  1. Resolve the previous release tag `contracts/{name}/vX.Y.Z` strictly
     older than the entry's current `full_version` (harness.tags).
  2. If there is no earlier tag: **first release** -- the N-1 leg is
     vacuously green (explicit pytest.skip, not a silent pass).
  3. Otherwise, run the two-leg ADR-0012 check:
       - leg 1: every valid fixture instance at the previous tag must
         still validate against the *current* schema (backward compat).
       - leg 2: harness.rules.judge() on the structural diff between the
         previous-tag schema and the current schema.

Registry currently has 38 active entries (26 from Wave 1 first release +
12 landed by w4-10 Contracts Steward). Because no prior
`contracts/{name}/v*` tags exist yet, every entry takes the explicit
first-release skip path (pytest.skip per entry — not a silent pass). A
dedicated meta-test still exercises the empty-registry bootstrap-skip
branch so an empty registry can never silently green.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from harness import registry as registry_mod
from harness import rules as rules_mod
from harness import tags as tags_mod
from harness import util as util_mod
from harness.diff import structural_diff

if TYPE_CHECKING:
    from harness.registry import RegistryEntry

BOOTSTRAP_SKIP_REASON = "registry has no entries yet (W1 bootstrap)"


def _load_registry_entries() -> list[RegistryEntry]:
    """Load registry entries for parametrization.

    Falls back to an empty list (rather than raising at collection time)
    if registry.json is somehow unreadable/invalid -- collection-time
    failures for the whole module would obscure the intended
    bootstrap-skip behavior; a broken registry is instead caught by
    tests/contract/validate/test_registry.py (w1-11), not this module.
    """
    try:
        return registry_mod.load_registry()
    except Exception:
        return []


_ENTRIES = _load_registry_entries()


def _run_check_jsonschema(
    schema_path: Path, instance_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "check-jsonschema",
            "--schemafile",
            str(schema_path),
            str(instance_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _check_n1_compat_for_entry(entry: RegistryEntry) -> None:
    """The actual per-entry N-1 compat check, factored out so the meta-test
    below can exercise the bootstrap-skip branch directly without
    depending on pytest's parametrize/skip collection reporting.
    """
    tag = tags_mod.previous_tag(entry.name, entry.full_version)
    if tag is None:
        pytest.skip(
            f"no prior tag contracts/{entry.name}/v* -- first release, N-1 leg vacuously green"
        )

    schema_path = registry_mod.schema_file_path_for_entry(entry)
    current_schema_bytes = schema_path.read_bytes()
    current_schema = json.loads(current_schema_bytes)

    old_schema_relpath = str(schema_path.relative_to(tags_mod.repo_root())).replace("\\", "/")
    old_schema_bytes = tags_mod.load_at_tag(tag, old_schema_relpath)
    old_schema = json.loads(old_schema_bytes)

    old_major = int(tag.rsplit("/v", 1)[1].split(".", 1)[0])

    # --- leg 1: previous-tag valid fixtures still validate against current schema
    fixture_paths = tags_mod.list_fixture_paths_at_tag(tag, entry.name)
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        for relpath in fixture_paths:
            instance_bytes = tags_mod.load_at_tag(tag, relpath)
            instance_data = json.loads(instance_bytes)
            stripped = util_mod.strip_metadata(instance_data)
            out_path = tmp_dir / Path(relpath).name
            out_path.write_text(json.dumps(stripped), encoding="utf-8")

            result = _run_check_jsonschema(schema_path, out_path)
            assert result.returncode == 0, (
                f"{entry.name}: N-1 fixture {relpath} (from {tag}) no longer validates "
                f"against current schema {schema_path}:\n"
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )

    # --- leg 2: structural diff + rules.judge()
    findings = structural_diff(old_schema, current_schema)
    verdict = rules_mod.judge(
        entry=entry,
        old_schema_bytes=old_schema_bytes,
        new_schema_bytes=current_schema_bytes,
        structural_findings=findings,
        old_major=old_major,
        new_major=entry.major,
    )
    assert verdict.verdict == "pass", (
        f"{entry.name}: N-1 compat verdict={verdict.verdict!r} reasons={verdict.reasons} "
        f"findings={findings}"
    )


@pytest.mark.parametrize(
    "entry",
    _ENTRIES if _ENTRIES else [pytest.param(None, id="bootstrap-empty-registry")],
)
def test_n1_compat(entry: RegistryEntry | None) -> None:
    if entry is None:
        pytest.skip(BOOTSTRAP_SKIP_REASON)
    _check_n1_compat_for_entry(entry)


# --------------------------------------------------------------------------
# Meta-test: prevent silent no-op when the registry is empty.
# --------------------------------------------------------------------------


def test_bootstrap_skip_branch_is_exercised_when_registry_empty() -> None:
    """Directly assert the bootstrap-skip branch fires for an empty
    registry, independent of the module-level `_ENTRIES` parametrization
    above (which only proves *this* run's registry state, not the
    branch's behavior in general). This is the "meta-test" required by
    the plan so an empty registry can never silently produce a green
    suite with zero assertions run.
    """
    with pytest.raises(pytest.skip.Exception) as exc_info:
        test_n1_compat(None)
    assert BOOTSTRAP_SKIP_REASON in str(exc_info.value)


def test_registry_entries_loaded_without_swallowing_real_errors() -> None:
    """Sanity check that `_load_registry_entries()`'s defensive try/except
    is not silently hiding a genuinely broken registry.json -- the actual
    registry must load cleanly via the non-defensive path too.
    """
    entries = registry_mod.load_registry()
    assert entries == _ENTRIES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
