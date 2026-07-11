# ADR-0021: SBOM & dependency policy — CycloneDX + syft + osv-scanner, dormant-but-armed CI

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

의존성 공급망 가시성(SBOM)·취약점 스캔·핀 강제·license 정책을 언어 결정(ADR-0009) 이전에도 CI에 미리 배선하되, lockfile이 없는 동안은 안전하게 성공-스킵하도록 확정한다.

## Scope

In: SBOM 포맷·생성 도구, 취약점 스캐너, pinning 규칙(lockfile/hash/Actions SHA/devcontainer digest), license allowlist 3단계.
Out: 법무 최종 sign-off(별도 항목, design §13-5 연계 — 아래 명시), 언어별 실제 lockfile 생성(ADR-0009/T06 소관).

## Context

- 계획 §1 "SBOM/의존성" 항목: 언어 미확정 기간에도 CI action 자체가 공급망 표면이므로, lockfile 부재를 이유로 CI 배선을 미루지 않는다 — 대신 "dormant-but-armed"로 만든다.
- security-model.md 제약: "SBOM + signature + pinned third-party skills".
- dependency-policy.md 규칙 5: "No dependency install by agents without pin + allowlist (runtime policy)" — 이 ADR이 그 pin/allowlist를 구체화한다.
- ADR-0009가 Python 3.12 + uv, TypeScript는 operator-console 한정으로 확정했으므로 pinning 규칙은 두 생태계 모두 대비한다.

## Current decision

### SBOM 포맷·도구

- **CycloneDX 1.6** 을 1차 포맷으로 생성 — **syft**로 생성(SPDX export 가능, 특정 도구 lock-in 없음).
- 취약점 스캔은 **osv-scanner**.

### Dormant-but-armed CI

- lockfile이 아직 존재하지 않는 현재는 SBOM/scan job이 **성공-스킵**(lockfile 부재 감지 시 조기 종료, exit 0) — CI를 막지 않는다.
- 첫 lockfile(`uv.lock` 또는 `package-lock.json`)이 등장하는 순간 같은 job이 자동으로 무장(arm)되어 실제 스캔을 수행한다. 별도 재활성화 커밋 불필요.

### Pinning 규칙

| 대상 | 규칙 |
|---|---|
| Python | `uv.lock` 필수 + CI `uv sync --locked`로 lockfile-manifest 일치 강제. hash pinning(`--require-hashes`) |
| Node (operator-console/AsyncAPI CLI 도구용) | `npm ci`-style만 허용(`npm install` 직접 CI 사용 금지) — lockfile-manifest 불일치 시 실패 |
| GitHub Actions | 전 action **full commit SHA pin** — `zizmor`로 CI에서 강제 lint |
| devcontainer base image | digest pin(태그가 아닌 sha256 digest) |

### License 정책 (3단계, W0 engineering interim)

| 등급 | License |
|---|---|
| ALLOW | MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, 0BSD, PSF-2.0, CC0-1.0, Unlicense |
| MANUAL-REVIEW | MPL-2.0, EPL-2.0, LGPL 계열 |
| BLOCK | GPL, AGPL, SSPL, BUSL, Commons-Clause, 식별 불가 license |

이 표는 사용자가 2026-07-12 확정한 **W0 엔지니어링 interim** 값이다. 최종 법무 sign-off는 별도 항목으로 design §13-5(license/GRS 관련 결정)와 연계되어 남아 있으며, 법무 검토 완료 전까지 이 표가 CI enforcement 기준이 된다. 법무 결과가 이 표와 달라지면 이 ADR을 개정한다.

## Constraints

- 첫 lockfile 등장 시점부터 enforcement 활성 — 그 전에는 SBOM/license job이 데이터를 생성하지 않는다(성공-스킵이 곧 "미검증"이 아니라 "대상 없음"임을 CI 로그에 명시).
- Actions SHA pin·zizmor는 CI 소유(Integrator 단독, `.github/**`) — 이 ADR은 규칙만 정의하고 실제 workflow 배선은 T17 소관.
- devcontainer digest pin은 ADR-0022와 연동.

## Open decisions

- license 표 최종 법무 sign-off — design §13-5, 별도 법무 검토 항목(계획 §8-16).

## Source specification references

- `docs/architecture/dependency-policy.md` 규칙 5
- `docs/architecture/security-model.md` (SBOM + signature + pinned third-party skills)
- `docs/decisions/ADR-0009-language-stack.md` (Python/uv, TypeScript 범위)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.
