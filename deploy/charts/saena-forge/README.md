# saena-forge Helm chart

## Purpose

The `saena-forge` Helm chart (ADR-0005 confirmed chart identity) — control-
plane manifests for the 8 independently-deployed services (of the 24
logical-capability catalog; service-catalog.md "Independent Deployment"
rendering class), namespaces, default-deny NetworkPolicy, scoped RBAC, and
the 6 required Grafana dashboards. Internal B-department tool only, not a
customer deployment product (k3s spec §1).

## Layout

```text
deploy/charts/saena-forge/
├── Chart.yaml
├── values.yaml                  # production-leaning defaults
├── values.schema.json           # engine-scope closed enum + digest-pin +
│                                 # secret-reference-only enforcement
├── dashboards/                  # 6 required Grafana dashboards (JSON model)
│   ├── 01-workflow.json
│   ├── 02-safety.json
│   ├── 03-quality.json
│   ├── 04-aeo.json
│   ├── 05-cost.json
│   └── 06-drift.json
└── templates/
    ├── _helpers.tpl
    ├── namespaces/               # saena-system/data/observability + tenant template
    ├── network-policies/         # default-deny + explicit allow rules
    ├── config/                   # infra-connection ConfigMap + ExternalSecret refs
    ├── services/                 # Deployment/Service/ServiceAccount/PDB per service
    ├── rbac/                     # namespace-scoped Role/RoleBinding per service + agent-runner
    └── dashboards/                # ConfigMap wrapper mounting dashboards/*.json
```

## Decisions (w2-23)

- **Dashboards-as-code location**: `deploy/charts/saena-forge/dashboards/`
  (chart-root, not under `templates/`) holds the raw Grafana dashboard JSON
  model files as the human-edited source of truth. `templates/dashboards/
  grafana-dashboards-configmap.yaml` reads them via Helm's `.Files.Get` (byte
  -for-byte, untemplated) and wraps each in its own ConfigMap labeled per the
  Grafana sidecar discovery convention (`grafana_dashboard: "1"`,
  `.Values.observability.grafana.dashboardSidecarLabel`/`...LabelValue`).
  One ConfigMap per dashboard (not one combined ConfigMap) keeps each well
  under the ~1MiB ConfigMap size limit and lets Grafana's sidecar
  file-watcher track per-dashboard changes independently. Chosen over
  `deploy/observability/dashboards/` because dashboards are versioned
  together with the chart/release that defines the metrics they chart —
  splitting them into a separate top-level tree would decouple that version
  lock (k3s spec §1's four-artifact lock: image digest / migration version /
  policy bundle / skill bundle — dashboards are a fifth thing that should
  move with the chart, not drift independently).
- **External data dependencies (Postgres/Temporal/MinIO/Redpanda) are
  CONNECTION config only, not bundled subcharts** — `postgres.external:
  true` / `objectStorage.external: true` etc. in `values.yaml`, matching the
  k3s spec §7 skeleton and ADR-0007 D-6 (Wave 2 infra staging = managed/
  external, not in-chart). Every credential is a `*SecretRef` name pointing
  at an `ExternalSecret` object (`templates/config/external-secret-refs.yaml`)
  — no credential VALUE is ever declared in this chart (ADR-0020).
- **RBAC is namespace-scoped Role/RoleBinding, never ClusterRole** — each of
  the 8 services and the `agent-runner` ServiceAccount gets its own `Role`
  with an explicit `rules` list from `values.yaml`; no wildcard verb/
  resource anywhere in this chart (k3s spec §8.1 condition 5 / security-
  model.md).

## Validation

```bash
helm lint deploy/charts/saena-forge
helm template saena-forge deploy/charts/saena-forge
uv run python3 -m saena_forgectl preflight --values deploy/charts/saena-forge/values.yaml
uv run pytest tests/unit/deploy -q
```

Static Kubernetes-manifest schema validation: `kubeconform -strict
-kubernetes-version 1.29.0 -ignore-missing-schemas` against the rendered
`helm template` output (no live cluster contacted). `kubectl apply
--dry-run=client` was considered but not used as the primary method in this
sandboxed environment (see `tests/unit/deploy/test_static_manifest_validation.py`
docstring); `kubeconform` needs no kubeconfig/API-server reachability at all.

## Out of scope (this unit, w2-23)

- Rollback smoke testing against a live k3d cluster — separate unit (w2-25).
- `deploy/profiles/**` values overlays (dev/staging/prod/airgap) — this
  chart's `values.yaml` is the production-leaning baseline; profile-specific
  overlays are a follow-up.
- Live-cluster verification (`--verify-signatures`, `--check-network-policy`,
  etc.) — `forgectl preflight` accepts these flags as documented no-ops
  today (`tools/forgectl/README.md`).

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1, §3–4, §6, §7,
  §8.1, §9.2
- `docs/architecture/service-catalog.md`, `deployment-profiles.md`,
  `data-ownership.md`, `security-model.md`, `observability.md`
- ADR-0004 (node pools), ADR-0007 (tenant namespace/ownership), ADR-0014
  (tenant propagation/namespace derivation), ADR-0020 (secret scanning/
  lifecycle), ADR-0021 (SBOM/dependency pinning discipline)

## Status

IMPLEMENTED (w2-23) — chart + 6 dashboards, human-approved write to this
protected path. `forgectl preflight` PASS (Google off) / FAIL (Google on).
