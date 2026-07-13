"""pytest fixtures for `tests/unit/svc_quality_eval`.

Two `sys.path` insertions (same isolation pattern as
`tests/unit/svc_artifact_registry/conftest.py`'s own docstring precedent —
a same-named `conftest` module collision across test directories has bitten
this repo before, so sibling factory helpers live under a uniquely-named
module, never a second `conftest.py`):

1. `_THIS_DIR` — so sibling test modules can `from factories import ...`.
2. `_SERVICE_SRC_DIR` (`services/platform/quality-eval-service/src`) —
   `saena_quality_eval` is NOT YET a registered `[tool.uv.workspace]`
   member (root `pyproject.toml` is outside this patch unit's exclusive
   write paths, per this unit's own scope boundary — every other Wave 3
   sibling unit under active development would collide on that same file if
   each independently added its own workspace-member line). Until an
   Integrator adds `services/platform/quality-eval-service` to root
   `pyproject.toml`'s `[tool.uv.workspace].members` +
   `[dependency-groups].dev` + `[tool.uv.sources]` (mirroring every other
   `services/platform/*-service` entry there), this explicit `sys.path`
   insertion is how this test suite imports `saena_quality_eval` at all —
   see this patch unit's final report "Integrator actions".
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_SERVICE_SRC_DIR = (
    _THIS_DIR.parent.parent.parent / "services" / "platform" / "quality-eval-service" / "src"
)

for _path in (_THIS_DIR, _SERVICE_SRC_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from factories import (  # noqa: E402
    TENANT_A,
    build_approved_change_plan,
    build_gate_input_bundle,
    build_patch_artifact_manifest,
    build_quality_eval_request,
)
from saena_domain.persistence import InMemoryArtifactManifestStore  # noqa: E402


@pytest.fixture
def manifest_store() -> InMemoryArtifactManifestStore:
    return InMemoryArtifactManifestStore()


@pytest.fixture
def approved_change_plan() -> dict[str, object]:
    return build_approved_change_plan()


@pytest.fixture
def patch_artifact_manifest() -> dict[str, object]:
    return build_patch_artifact_manifest()


@pytest.fixture
def gate_input_bundle():
    return build_gate_input_bundle()


@pytest.fixture
def quality_eval_request(gate_input_bundle):
    return build_quality_eval_request(gate_inputs=gate_input_bundle)


@pytest.fixture
def tenant_id() -> str:
    return TENANT_A
