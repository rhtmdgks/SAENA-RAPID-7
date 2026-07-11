# Observability

## Purpose

Observable-by-default requirements.

## Scope

Traces, metrics, logs, audit envelope, dashboards, retention.

## Current decision

**CONFIRMED** intent: OpenTelemetry; required dashboards; run trace envelope fields in k3s §9.

## Run trace envelope (CONFIRMED fields)

`trace_id`, `run_id`, `tenant_id`, `repo_sha`, `chart_version`, `image_digests`, `policy_bundle_hash`, `skill_bundle_hash`, `action_contract_hash`, `model_adapter`, `events`

## Dashboard themes (CONFIRMED)

Workflow lead time; Safety denies; Quality gates; AEO layers; Cost; Drift

## Rendering (CONFIRMED — ADR-0002 rev.3 / ADR-0007)

observability capability = **기성 스택**: OTel Collector + Prometheus/Loki/Tempo + Grafana dashboards-as-code + Alertmanager webhook adapter (`slo.alert.fired.v1` 발행용 얇은 계층). 자체 마이크로서비스 아님 — 계약·책임(대시보드 6종, SLO, drift)은 유지, 소유는 SRE + emit 서비스로 재배분. 도입 = W2C.

## Cost/usage telemetry (v1 — UsageRecord 계약 불요)

집행 = agent-runner `maxCostUsdPerRun` / 관측 = OTel cost 메트릭 + per-tenant budget 대시보드 / 정책 소유 = tenant-control. billing 계약(UsageRecord)은 P2.

## Constraints

- No secrets in telemetry payloads
- Audit completeness 100% for success declaration
- Tenant labels required — 3-context 분류(ADR-0006 rev.2): SystemContext 텔레메트리는 tenant label 면제
- Consumer lag·outbox 적체 알람 필수 (resilience.md)

## Open decisions

- Exact backend trio (Prometheus/Loki/Tempo vs alternatives) per profile — PROPOSED in values skeleton

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §9
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.6

## Status

CONFIRMED requirements / NOT IMPLEMENTED
