# tools/forgectl

## Purpose

`forgectl` — the SAENA FORGE k3s package operator CLI. This patch unit
(w2-19, W2C exit) delivers `forgectl preflight`: the static-config gate the
k3s Package and Operations Spec §8.1 requires before any `helm upgrade
--install saena-forge …` is attempted.

## Scope

In: `forgectl preflight --values <path>` — parses a declarative Helm values
YAML and runs six independent, structured checks against it. Exit 0 iff
every check passes; non-zero otherwise, with the specific failed check(s)
named in both the human-readable report and `--json` output.

Out (documented extension point, not implemented here): live-cluster
checks. W2A has no running cluster to query — this preflight is **static**:
it evaluates the *declared* configuration in the values file, not runtime
state (an actual signature-verify call against a registry, an actual
`NetworkPolicy` object read from the API server, an actual RoleBinding
lookup). Wiring those live checks is future work once a cluster exists;
each check function here is written so a live variant can be added
alongside it without changing the `CheckResult` contract or the CLI.

## Checks (k3s spec §8.1 — preflight MUST fail if...)

1. `image_digest_signature` — required image digest or signature is absent
2. `engine_flags` — engine flags include any Google AI service in v1
   (**the named W2C exit gate** — CLAUDE.md Engine scope v1; the v1 closed
   enum is `saena_schemas.common.engine_id_v1.EngineId`, currently
   `{chatgpt-search}` only)
3. `external_secrets` — external secret references resolve to plaintext
   ConfigMap values
4. `network_policy` — default-deny NetworkPolicy is absent
5. `service_account_permissions` — runner service account has
   `cluster-admin` or production deploy permission
6. `migrations_reversible` — migrations are non-reversible or unreviewed

## Values file shape

Mirrors the k3s spec §7 Helm values skeleton (`global.engineScope`,
`global.policyBundle.digest`, `global.network.defaultDeny`, ...). See
`tests/unit/forgectl/fixtures/values-passing.yaml` for a fully-annotated
passing example and the sibling `values-fail-*.yaml` fixtures for each
individual failure mode.

## Usage

```bash
uv run python3 -m saena_forgectl preflight --values path/to/values.yaml
uv run python3 -m saena_forgectl preflight --values path/to/values.yaml --json
uv run python3 -m saena_forgectl --version
```

Exit codes: `0` = every check passed. `1` = one or more checks failed.
`2` = the values file could not be parsed/loaded (malformed YAML, missing
file, non-mapping document) — a distinct code from a normal check failure
so CI can tell "your config is wrong" apart from "your config was readable
and rejected".

## Packaging note

`tools/forgectl` **is** a `uv` workspace member (root `pyproject.toml`
`[tool.uv.workspace]` members, `[tool.uv.sources]`, dev-group dependency
`saena-forgectl`; root `[tool.mypy]` files and `[tool.coverage.run]` source
cover it; `.importlinter` `root_packages` carries `saena_forgectl` with a
leaf/boundary contract — may import `saena_schemas`, must not be imported by
`saena_domain` or any service). Registered by w2-20 (Wave 2 exit, Integrator
root-config edit) — the originating patch unit (w2-19) deliberately left it
out because doing so required root-config edits outside that unit's
exclusive write paths (`tools/forgectl/**`, `tests/unit/forgectl/**` only).
`tests/unit/forgectl/conftest.py` still inserts `tools/forgectl/src` onto
`sys.path` directly (idempotent no-op now that the workspace editable
install already puts `saena_forgectl` on `sys.path`) — left as-is by w2-20,
mirroring the existing `tests/unit/domain_identity` /
`tests/unit/svc_engine_gateway` "tests/ is not a package" convention.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §7 (values
  skeleton), §8.1 (preflight command + fail conditions)
- `docs/architecture/implementation-waves.md` W2C exit ("`forgectl
  preflight` 통과, Google flag on 시 fail 포함")
- CLAUDE.md Engine scope (v1): ChatGPT Search only
- `packages/schemas/saena_schemas/common/engine_id_v1` (generated v1 closed
  enum, reused here as the engine-flag check's source of truth)

## Status

CONFIRMED — `forgectl preflight` implemented (static config gate). Live-cluster
checks NOT IMPLEMENTED (documented extension point above).
