# deploy/

## Purpose

Helm charts, profiles, policies, environments. Protected path.

## Scope

charts/, profiles/, policies/. (environments/는 ADR-0007로 삭제 — 환경 구분은 profiles × values overlay 단일 축)

## Current decision

CONFIRMED Helm/OCI packaging intent.

**CONFIRMED (2026-07-12, user decision):** official Helm chart name is `saena-forge`. Not used: `forge` (collision-prone), `saena-forge-chart` (redundant suffix). Specs use both older forms; this decision supersedes them for implementation.

**IMPLEMENTED (w2-23, human-approved write to this protected path):** `deploy/charts/saena-forge/` — Chart.yaml, values.yaml, values.schema.json (engine-scope closed enum + digest-pin + secret-reference-only enforcement), templates/ for the 8 independently-deployed services (namespaces, default-deny NetworkPolicy + explicit allow rules, Deployment/Service/ServiceAccount/scoped RBAC/PodDisruptionBudget per service, ExternalSecret references, infra-connection ConfigMap), and the 6 required Grafana dashboards (`deploy/charts/saena-forge/dashboards/`, mounted via a per-dashboard ConfigMap template using the Grafana sidecar label convention). `helm lint`/`helm template` clean; `forgectl preflight` passes (Google flag off) and fails (Google flag on); static manifest validation via `kubeconform -strict`. See `tests/unit/deploy/` for the chart-validation test suite. Rollback smoke testing against a live k3d cluster is a separate unit (w2-25) — NOT covered here.

## Constraints

- Agents: no kubectl apply / helm upgrade
- Values reference secrets only

## Open decisions

- (chart identity — RESOLVED, see Current decision above)

## Source specification references

- k3s §2, §7–8

## Status

`charts/saena-forge/` IMPLEMENTED (w2-23) / `profiles/`, `policies/` still skeleton, NOT IMPLEMENTED
