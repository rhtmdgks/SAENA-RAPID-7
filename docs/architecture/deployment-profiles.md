# Deployment profiles

## Purpose

Separate deployment profiles without leaking into algorithm code.

## Scope

Four bootstrap profiles + relation to k3s operational profiles.

## Current decision

**CONFIRMED principles**

- Same SAENA Core container images across profiles
- Environment configuration + infrastructure adapters separated
- `internal-k3s` still uses `tenant_id` (fixed/single-operator) threaded through contracts
- SaaS: per-tenant data/cache/event/workflow namespace isolation
- Customer source only in per-execution isolated workspace
- Central API server does not directly modify customer code
- Deployment profile must not penetrate algorithm code

**PROPOSED profile folder set** (this repo)

| Profile | Path | Intent |
|---|---|---|
| development | `deploy/profiles/development/` | local/k3d skill-eval; customer source forbidden |
| internal-k3s | `deploy/profiles/internal-k3s/` | B부서 production-shaped package |
| saas-shared | `deploy/profiles/saas-shared/` | future multi-tenant shared SaaS |
| saas-dedicated | `deploy/profiles/saas-dedicated/` | future dedicated SaaS |

k3s spec also describes Developer / Internal Staging / Internal Production / Air-gap operational profiles — map onto the above via values overlays (**PROPOSED** mapping).

## Constraints

- Helm values reference secrets; never embed secret material
- v1 engine flags: chatgptSearch true; google/gemini false
- Agent runners: Jobs with TTL destroy
- OUT OF SCOPE now: real SaaS auth/billing/metering code

## Environments 축 통합 (ADR-0007, 2026-07-12)

구 `deploy/environments/`는 삭제됨 — 환경 구분(dev/staging/prod/airgap 오버레이)은 **profiles × values overlay 단일 축**으로 표현한다 (k3s §5 운영 프로파일은 각 profile 폴더의 values 오버레이로 매핑). 축 중복(plat D6) 종결.

## Open decisions

- Air-gap as subset of internal-k3s vs separate profile folder — OPEN DECISION
- SaaS tenancy billing model — OUT OF SCOPE / OPEN DECISION (usage/quota 소유는 tenant-control로 확정 — ADR-0007)

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5, §7
- User bootstrap requirements §6

## Status

CONFIRMED principles / PROPOSED folder names / NOT IMPLEMENTED charts
