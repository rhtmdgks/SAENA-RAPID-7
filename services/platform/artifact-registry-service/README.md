# artifact-registry-service

| Field | Value |
|---|---|
| Service name | `artifact-registry-service` |
| Bounded context | Run artifact storage |
| Primary responsibility | patch, PR bundle, screenshots, raw responses, reports |
| Owned data | object manifest |
| Consumed contracts | artifact uploads; content hashes |
| Published events | artifact.registered.v1 (PROPOSED) |
| Consumed events | patch.unit.completed.v1; observation.captured.v1; quality.gate.* |
| Upstream dependencies | agent-runner-service; chatgpt-observer-service; quality-eval-service |
| Downstream consumers | forge-console-api; audit-ledger-service |
| Security boundary | tenant-scoped object storage; content-hash addressing |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **PARTIAL — W2B blob single-gateway + manifest API (w2-16)** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/implementation-waves.md` W2B exit criterion ("blob 단일 관문 검증", "manifest 불변성")
- `docs/architecture/data-ownership.md` ("manifest = artifact-registry, blob 쓰기 단일 관문 = artifact-registry")
- `docs/architecture/contract-catalog.md` PatchArtifact row (idempotency key `patch_unit_id+worktree_commit`)
- ADR-0024(f) (uri fields reject `?`/`#` — presigned-token structural ban)
- ADR-0007 (object storage tenant path prefix)
- ADR-0015 (RFC 9457 canonical error model)

## Status

PARTIAL (w2-16) — `saena_artifact_registry` package implements:

- Blob single-gateway store (`blobstore.py`): `BlobStore` Protocol +
  `InMemoryBlobStore` (reference adapter) + `MinioBlobStore` (real MinIO
  adapter, ADR-0007 tenant path-prefix object keys, unit-tested via an
  injected fake client — no docker/live MinIO required for this patch
  unit). Blob references are opaque (`blob:<tenant_id>:<sha256>`), never a
  URL or presigned token.
- FastAPI app factory `create_app(manifests, blobs)` (`app.py`):
  `POST /v1/artifacts` (register manifest + blob, put-once by
  `patch_unit_id+worktree_commit`, server-computed `sha256`),
  `GET /v1/artifacts/{patch_unit_id}/{worktree_commit}` (manifest lookup),
  `GET /v1/artifacts/{patch_unit_id}/{worktree_commit}/blob` (gated blob
  fetch, tenant-checked).
- RFC 9457 `application/problem+json` error responses (`problem.py`,
  `errors.py`) built from the generated `ProblemDetail` contract model.
- ADR-0024(f) uri-field structural validation (`uri_validation.py`),
  defense-in-depth alongside the generated `PatchArtifact` model's own
  `UriRef` pattern.
- Tenant-safe logging: only hash/size attributes are logged, never blob
  content or manifest bytes (customer-proprietary MAX sensitivity,
  contract-catalog.md "diff=소스").

NOT in this patch unit's scope: SQL/real persistence adapters (w2-13), bus
publisher wiring for `artifact.registered.v1` (w2-18), k3s Deployment
manifest, Dockerfile, real-MinIO integration test (optional, skip-if-unavailable).
