"""pytest fixtures for `tests/unit/svc_artifact_registry`.

`tests/` is not a package — this directory is inserted onto `sys.path` so
sibling test modules can `from registry_factories import ...` (same
isolation pattern as `tests/unit/domain_persistence/conftest.py`: a
same-named `conftest` module collision across test directories has bitten
this repo before, see that module's own docstring — factory helpers here
therefore live under a uniquely-named module, never a second `conftest.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from registry_factories import TENANT_A, build_manifest_fields  # noqa: E402
from saena_artifact_registry import InMemoryBlobStore, create_app  # noqa: E402
from saena_domain.identity.http import TENANT_HEADER_NAME  # noqa: E402
from saena_domain.persistence import InMemoryArtifactManifestStore  # noqa: E402


@pytest.fixture
def manifests() -> InMemoryArtifactManifestStore:
    return InMemoryArtifactManifestStore()


@pytest.fixture
def blobs() -> InMemoryBlobStore:
    return InMemoryBlobStore()


@pytest.fixture
def client(manifests: InMemoryArtifactManifestStore, blobs: InMemoryBlobStore) -> TestClient:
    app = create_app(manifests, blobs)
    return TestClient(app)


@pytest.fixture
def tenant_headers() -> dict[str, str]:
    return {TENANT_HEADER_NAME: TENANT_A}


@pytest.fixture
def manifest_fields() -> dict[str, object]:
    return build_manifest_fields()
