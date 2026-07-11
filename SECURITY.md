# SECURITY

## Purpose

보안 경계·보고·금지 사항 요약.

## Scope

SAENA FORGE package, agent runners, tenant isolation, supply chain.

## Current decision

CONFIRMED principles from k3s ops + harness design. Implementation NOT IMPLEMENTED.

## Constraints

- NetworkPolicy default-deny
- Non-root runners; short-lived credentials; TTL workspace destroy
- Secrets never in Helm values, ConfigMaps, image layers, prompts, audit payloads
- Production deployment credentials **never** registered in FORGE
- Customer Git starts read-only; write/PR token only after B approval + lease
- Untrusted web content quarantined; never treated as instructions
- **LLM provider egress는 격리 모델의 명시적 예외 (2026-07-12 감사)**: 실행(Execution) 단계에서 고객 소스가 승인된 model provider(api.openai.com, api.anthropic.com — Algorithm §10 allowlist)로 프롬프트 컨텍스트로 전달되는 경로는 spec에 이미 존재하는 유일한 상시 예외다. 이 예외는 **실행 단계에 한정**되며 Strategy Skill Bank 학습 파이프라인에는 절대 확장되지 않는다 (Algorithm 원칙 6: 학습에는 익명화된 결과 메타데이터만). Provider data retention 정책 확정은 design §13-4 OPEN DECISION — 확정 전 이 예외를 근거로 한 추가 데이터 경로 신설 금지
- Third-party skills: pinned SHA + SBOM + internal mirror only
- v1 engine: ChatGPT Search only; Google/Gemini adapters disabled

## Protected concerns

- AuthN/Z, tenant isolation, policy bundles
- `deploy/policies/**`, NetworkPolicy, RBAC
- Secret broker / workload identity

## Reporting

**CONFIRMED (2026-07-12, user decision):** primary private reporting channel is **GitHub Private Vulnerability Reporting (GitHub Security Advisory)** on this repository.

Do **not** report vulnerabilities via:

- public GitHub Issues
- public GitHub Discussions

Security email: **PROPOSED** `security@saenalabs.com` — **not an active channel yet**. Do not use it for reports until the mailbox is created and passes a receipt test; upgrade to CONFIRMED only after that verification.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §6, §10
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.4–5.5

## Status

CONFIRMED principles / NOT IMPLEMENTED controls
