"""`RawArtifactGatewayPort` — the ONLY path raw observation content may
travel through on its way out of this package.

W4 hard constraint (this unit's own task instruction): "raw response HTML/
screenshot is NEVER stored inline in the observation. It is persisted
through the artifact-registry single gateway and the observation carries
only a content-addressed `raw_object_ref` + `artifact_hash`." This module
is that boundary, mirroring `saena_agent_runner.artifact.
ArtifactRegistryGateway`'s own "single-gateway Protocol + in-memory fake,
real HTTP adapter is later/separate glue code" precedent exactly (same
repo-wide convention) — `saena_chatgpt_observer` does not itself talk to
object storage, does not itself construct a `saena_artifact_registry.
blobstore.BlobRef`, and does not depend on the `saena-artifact-registry`
package at all (that would reach outside this unit's exclusive write paths
as a new hard pyproject dependency); it only fixes the call SHAPE a real
adapter (calling artifact-registry-service's published HTTP contract, wired
up by a later integration unit — see `tests/e2e/execution/
artifact_registry_adapters.py` for the established "HTTP adapter lives in
test/integration glue code" pattern) must satisfy.

`artifact_hash` reuses `saena_domain.audit.canonical.sha256_hex`'s SAME
underlying algorithm (task instruction: "reuse `saena_domain.audit.
canonical` sha256 for the hash") — `sha256_hex`'s own public signature is
`str -> UTF-8 bytes -> hashlib.sha256(...).hexdigest()`; it has no bytes-in
overload, and re-encoding raw binary content (HTML/screenshot bytes, not
UTF-8 text) through an intermediate `str` would silently corrupt the digest
for any byte sequence that is not valid UTF-8 (raw captured HTML can
legitimately contain such bytes). This module's `_hex_digest` therefore
calls `hashlib.sha256(...).hexdigest()` directly on the raw bytes — the
exact same standard-library primitive `sha256_hex` itself wraps, applied to
the one case (raw bytes, not a JSON-shaped Python object) that helper's own
`str`-typed signature does not cover — never a second, DIFFERENT hashing
algorithm.

`raw_object_ref` is always a `scheme://...` opaque URI (ADR-0024(f) common
uri-field pattern, the SAME `^[a-z0-9+.-]+://[^?#]+$` shape `saena_schemas.
domain.platform_observation_v1.UriRef` enforces) built as
`artifact://<tenant_id>/<sha256_hex>` — never a resolvable storage URL,
never a presigned token, mirrors `saena_agent_runner.artifact.
FakeArtifactRegistryGateway`'s own `blob://<tenant_id>/<hash>` ref shape
(different scheme name so this package's own raw-artifact refs are
trivially distinguishable in logs/audit trails from a `PatchArtifact`'s
`blob_uri`, but the SAME opaque, non-resolvable discipline).
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from saena_chatgpt_observer.errors import CrossTenantObservationError

_ARTIFACT_REF_SCHEME = "artifact"


@dataclass(frozen=True, slots=True)
class RawArtifactRef:
    """Opaque references a `RawArtifactGatewayPort.put_raw_artifact` call
    returns — a content-addressed ref + its sha256 hash, NEVER the raw
    bytes themselves (single-gateway invariant's structural guarantee, same
    shape as `saena_agent_runner.artifact.RegisteredArtifactRef`)."""

    raw_object_ref: str
    artifact_hash: str


def _hex_digest(raw_content: bytes) -> str:
    """Lowercase hex SHA-256 digest of `raw_content` (see module docstring
    for why this calls `hashlib.sha256` directly on the raw bytes rather
    than routing through `saena_domain.audit.canonical.sha256_hex`'s
    `str`-only signature — same underlying algorithm, applied to the one
    input shape that helper's own public contract does not cover)."""
    return hashlib.sha256(raw_content).hexdigest()


@runtime_checkable
class RawArtifactGatewayPort(Protocol):
    """Single-gateway boundary this package delegates ALL raw-artifact
    storage to. Exactly one method — a pure write-and-return-a-ref call,
    structurally distinct from the READ-ONLY `BrowserSessionPort`/
    `ObservationSourcePort` (this is the one place this package's data
    flows OUT to persistent storage; it never flows out to the ChatGPT
    account or any other external write target)."""

    def put_raw_artifact(self, *, tenant_id: str, raw_content: bytes) -> RawArtifactRef:
        """Persist `raw_content` (raw response HTML/screenshot bytes) under
        `tenant_id` through the artifact-registry single gateway and
        return its opaque, content-addressed `RawArtifactRef`.

        Implementations own actual blob storage (out of this package's
        scope) — this call is a black box from `saena_chatgpt_observer`'s
        point of view, same as `ArtifactRegistryGateway.register()` is
        from `saena_agent_runner`'s.
        """
        ...


class FakeArtifactGateway:
    """Deterministic in-memory `RawArtifactGatewayPort` — the ONLY
    implementation this patch unit's unit lane exercises. No real network/
    object-storage I/O. Tenant-scoped (mirrors `saena_artifact_registry.
    blobstore.InMemoryBlobStore`'s own tenant-keyed dict-of-dicts).
    `get_raw_artifact` lets a test read back exactly what was stored,
    gated the same way a real gateway's read path would be — never a
    production call site (the whole point of the single gateway is that
    the OBSERVATION itself never reads raw content back)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, bytes]] = {}
        self.put_calls: list[str] = []

    def put_raw_artifact(self, *, tenant_id: str, raw_content: bytes) -> RawArtifactRef:
        artifact_hash = _hex_digest(raw_content)
        with self._lock:
            self._store.setdefault(tenant_id, {})[artifact_hash] = bytes(raw_content)
        self.put_calls.append(tenant_id)
        return RawArtifactRef(
            raw_object_ref=f"{_ARTIFACT_REF_SCHEME}://{tenant_id}/{artifact_hash}",
            artifact_hash=f"sha256:{artifact_hash}",
        )

    def get_raw_artifact(self, *, tenant_id: str, ref: RawArtifactRef) -> bytes:
        """Read back stored bytes — test-assertion helper only. Raises
        `CrossTenantObservationError` (fail-closed, same "existence across
        tenants never leaked" discipline as `saena_artifact_registry.
        blobstore.BlobStore.get_blob`) if the ref does not resolve under
        `tenant_id`."""
        expected_prefix = f"{_ARTIFACT_REF_SCHEME}://{tenant_id}/"
        if not ref.raw_object_ref.startswith(expected_prefix):
            raise CrossTenantObservationError(
                "raw_object_ref does not belong to the requesting tenant",
                context={"requested_tenant_id": tenant_id},
            )
        artifact_hash = ref.raw_object_ref.removeprefix(expected_prefix)
        with self._lock:
            data = self._store.get(tenant_id, {}).get(artifact_hash)
        if data is None:
            raise CrossTenantObservationError(
                "no raw artifact stored for this tenant/hash",
                context={"requested_tenant_id": tenant_id},
            )
        return data


__all__ = [
    "FakeArtifactGateway",
    "RawArtifactGatewayPort",
    "RawArtifactRef",
]
