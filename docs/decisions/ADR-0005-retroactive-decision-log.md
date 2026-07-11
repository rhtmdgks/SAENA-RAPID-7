# ADR-0005: Retroactive record of user decisions (chart name, security channel, bootstrap provenance)

- Status: accepted
- Date: 2026-07-12
- Deciders: 사용자 (repo owner), 2026-07-12 세션

## Purpose

ADR 없이 문서에 직접 기록됐던 사용자 결정 2건을 소급 기록하고, bootstrap 근거 문서 부재의 처리 방침을 정한다. (감사 발견 boot B1·B2·B5)

## Scope

In: Helm chart 이름, 보안 취약점 보고 채널, "Bootstrap task §N" 인용 출처 처리.
Out: 결정 내용 자체의 재론.

## Current decision

1. **Helm chart 공식 이름 = `saena-forge`** (사용자 결정, 2026-07-12). `forge`(충돌 위험)·`saena-forge-chart`(중복 접미) 불사용. 두 spec의 상이한 표기(Algorithm §6.5 `saena/forge`, k3s §1 `saena-forge-chart`)에 대한 구현 해석은 본 ADR가 보유. 기록 위치: `deploy/README.md` Current decision.
2. **1차 보안 보고 채널 = GitHub Private Vulnerability Reporting (Security Advisory)** (사용자 결정, 2026-07-12). 공개 Issue/Discussion 금지. `security@saenalabs.com`은 PROPOSED — 수신 테스트 통과 전 활성 채널 아님. 기록 위치: `SECURITY.md` Reporting.
3. **Bootstrap 근거 문서 처리 (boot B1)**: "Bootstrap task §2/§5/§6/§11", "User bootstrap requirements" 인용 원문이 repo에 없음 — 해당 인용에 근거한 CONFIRMED 항목(deployment-profiles의 "Same SAENA Core container images" 등)은 원문이 `docs/`에 불변본으로 편입되기 전까지 **검증 불가 — 사실상 PROPOSED로 취급**한다. 편입 여부는 사용자 결정 대기.

## Constraints

- docs/specs/*_v1.md 원본 불변 — 본 ADR는 해석·운영 결정만 보유

## Open decisions

- bootstrap 요구 문서 원문의 docs/ 편입 (사용자 제공 필요)

## Source specification references

- `deploy/README.md`, `SECURITY.md`, `docs/architecture/deployment-profiles.md`
- 감사 보고서 H-8, boot B1·B2·B5

## Status

accepted (항목 1·2) / 항목 3은 편입 대기
