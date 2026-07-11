# ADR-0022: Dev environment — devcontainer digest pins + 2-tier local profile

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

AI agent 세션 재현성을 보장하는 devcontainer 사양과, 클러스터 유무에 따른 2단계 로컬 개발 프로파일을 확정한다.

## Scope

In: devcontainer base image·도구 핀, `.tool-versions`(mise) fallback, local profile Tier1/Tier2 정의.
Out: 실제 `.devcontainer/*`·`tools/development/*` 파일 생성(T14/T15 소관), k3d 실사용(W2A~), Playwright 이미지(W4 observer 소관).

## Context

- 계획 §1 "Devcontainer"/"로컬 프로파일" 항목: "AI agent 세션 재현성 = 증거 원칙의 전제" — 매 세션이 동일 도구 버전에서 실행되지 않으면 검증 결과의 재현성이 깨진다.
- k3s spec §5.1 Developer profile: 로컬 개발은 고객 source 접근 없이 synthetic fixture만 사용.
- ADR-0009가 Python 3.12 + uv 단일 primary, Node는 계약·CI 도구 전용(서비스 코드 미사용)으로 확정 — devcontainer 도구 구성이 이를 따른다.
- docker-in-docker는 Apple Silicon에서 불안정한 사례가 알려져 있어(계획 §7 위험 8) fallback을 문서화해 둔다.

## Current decision

### Devcontainer

- Base: `mcr.microsoft.com/devcontainers/python:3.12-bookworm`, **digest pin**(태그가 아닌 sha256).
- Dockerfile 레이어에서 버전 고정 설치: `uv`, `just`, `kubectl`, `helm`, `k3d`, `oasdiff`, `gitleaks`.
- docker-in-docker feature 포함(k3d 실행용, Tier2 대비).
- Node LTS 포함 — **"contract & CI tooling only"** 명시(AsyncAPI CLI 등, ADR-0011 소관 도구). 서비스 코드에는 사용하지 않는다(ADR-0009와 정합) — 사용자 승인됨.
- 이미지에 secret 없음 — grep으로 검증(T14 완료 조건).
- Playwright는 이 이미지에 포함하지 않는다 — **W4 observer 이미지로 이연**.

### `.tool-versions` (mise) fallback

devcontainer를 쓰지 않는 로컬 환경을 위한 비-container fallback. devcontainer에 고정한 도구 버전과 동일 값을 유지한다(drift 방지).

### 로컬 프로파일 2-tier

| Tier | 범위 | 사용 시점 | 구성 |
|---|---|---|---|
| Tier1 no-cluster | W0~W1 | 계약/스키마 작업, 유닛 테스트 | `uv sync` + `just test`/`just contracts-validate` — 클러스터 불필요 |
| Tier2 k3d dev | W0에서 정의, W2A~ 실사용 | 서비스 통합 실행 | k3d 단일 노드 + `deploy/profiles/development` values overlay + 인프라 의존성은 `tools/development/docker-compose.dev.yaml`(k3d 밖에서 실행) |

- 고객 source는 로컬에서 절대 사용 금지 — synthetic fixture만(k3s spec §5.1).
- 서브셋 실행 규약: `just dev-up <service...>`.

### docker-in-docker fallback

Apple Silicon에서 docker-in-docker가 불안정한 경우 host-run k3d(컨테이너 밖에서 k3d 직접 실행)로 대체하는 절차를 문서화해 둔다(`docs/architecture/dev-environment.md` 소관, T14/T15에서 구체화).

## Constraints

- devcontainer 내부에도 ADR-0019의 dev-repo deny hook을 유지 — devcontainer가 hook 우회 경로가 되지 않는다.
- k3d 왕복(create→get nodes→delete)은 즉시 파기 대상 — 이것 자체가 배포가 아니다(CLAUDE.md 원칙 10과 무관).
- `deploy/profiles/development/README.md` 신규 작성은 보호 경로(`deploy/**`) — 별도 인간 승인 필요(계획 §8-11).

## Open decisions

- devcontainer Node 포함 범위 확정은 이 ADR에서 승인 완료(계획 §8-17) — 향후 서비스 코드에 Node가 필요해지는 경우는 별도 ADR.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5.1 (Developer profile, synthetic fixture only)
- `docs/decisions/ADR-0009-language-stack.md` (Python/uv primary, Node 범위)
- `docs/architecture/security-model.md` (dev-repo hook 유지 원칙)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.
