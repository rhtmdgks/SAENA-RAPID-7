# repository-intake-service

| Field | Value |
|---|---|
| Service name | `repository-intake-service` |
| Bounded context | Customer source intake |
| Primary responsibility | Git/zip intake, commit pinning, SBOM·secret scan |
| Owned data | repository manifest |
| Consumed contracts | intake requests; read-only source credentials (leased) |
| Published events | repo.intaken.v1 |
| Consumed events | — |
| Upstream dependencies | forge-console-api |
| Downstream consumers | site-discovery-service; agent-runner-service |
| Security boundary | tenant-scoped secrets; secret scan before agent context |
| Planned runtime | k3s Deployment + Jobs (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **PARTIAL** — Input Gate core + FastAPI adapter (w3-02); real Git clone / secret-scan-tool / content-hash adapters deferred (W3-later/integration) |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.4 (Input Gate), §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/execution-runtime.md` (`JobKind.REPOSITORY_INTAKE` pool/SA/read-only facts)
- `packages/contracts/json-schema/domain/source-snapshot/v1/source-snapshot.schema.json`

## Status

PARTIAL (w3-02) — `src/saena_repository_intake/` implements the Algorithm
§5.4 Input Gate as a pure-domain core (`core.perform_intake`) behind
`typing.Protocol` adapter interfaces (`protocols.py`), a FastAPI `POST
/v1/intake` adapter (`app.py`, mirrors `artifact-registry-service`'s
shape), and in-memory reference adapters for the ports needing no real
external I/O (`memory.py`). Covers: reference-only `SourceSnapshot` intake
under `JobContext` (tenant/workspace/project), `sha256:` content-hash
verification, secret-scan-precedes-acceptance with redacted refusal,
closed `source_type`/uri-scheme allow-lists, inline-content rejection,
`content_hash`-keyed idempotency (contract-catalog.md SourceSnapshot
idempotency key), forbidden-URI (`?`/`#`) rejection, cross-tenant
rejection, `repo.intaken.v1` emission via `saena_domain.execution.
build_repo_intaken_payload`, and an audit event per decision. NOT YET
implemented: real Git clone, a real secret-scanning-tool adapter, real
content re-hashing (`SecretScanner`/`ContentHashVerifier` have no shipped
production adapter — see `protocols.py`'s module docstring); this package
is also not yet a registered `[tool.uv.workspace]` member or
`.importlinter` `root_packages` entry (Integrator action).
