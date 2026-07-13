"""Shared fixtures for the Wave 5 deploy integration lane (w5-21)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def chart_dir() -> Path:
    return _REPO_ROOT / "deploy" / "charts" / "saena-forge"


@pytest.fixture
def values_file() -> Path:
    return _REPO_ROOT / "deploy" / "charts" / "saena-forge" / "values.yaml"
