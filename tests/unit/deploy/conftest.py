"""Shared fixtures for the `deploy/charts/saena-forge` chart-validation
unit tests (w2-23).

`tests/` is not a package (no `tests/__init__.py`), mirroring the existing
`tests/unit/forgectl`/`tests/unit/domain_identity` convention — this
directory needs no `sys.path` insert of its own package (unlike
`tests/unit/forgectl/conftest.py`, there is no `saena_*` source package
here to import; these tests validate static chart artifacts — YAML/JSON
files — using `pyyaml`/`jsonschema`, both already dev-group dependencies,
plus `saena_forgectl` itself for the forgectl-preflight proof test) so only
fixture-path helpers are provided.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
CHART_DIR = _REPO_ROOT / "deploy" / "charts" / "saena-forge"
DASHBOARDS_DIR = CHART_DIR / "dashboards"
VALUES_PATH = CHART_DIR / "values.yaml"
VALUES_SCHEMA_PATH = CHART_DIR / "values.schema.json"


@pytest.fixture
def chart_dir() -> Path:
    return CHART_DIR


@pytest.fixture
def dashboards_dir() -> Path:
    return DASHBOARDS_DIR


@pytest.fixture
def values_data() -> dict[str, Any]:
    with VALUES_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data


@pytest.fixture
def values_schema() -> dict[str, Any]:
    import json

    with VALUES_SCHEMA_PATH.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data
