# Requirements traceability matrix

## Purpose

Map bootstrap artifacts to design requirements.

## Scope

Bootstrap scaffolding coverage plus delivered-wave traceability (the Wave 6
rows below track IMPLEMENTED deliverables, not scaffolding).

## Current decision

CONFIRMED for the delivered Wave 6 rows; PROPOSED for the earlier
scaffolding-verification rows retained for history.

| Requirement | Source | Bootstrap artifact | Status |
|---|---|---|---|
| 24 microservices named | Algorithm §6.2 | `services/**`, service-catalog.md | CONFIRMED mapping / NOT IMPLEMENTED code |
| ChatGPT Search only v1 | All specs | CLAUDE.md, adapters, feature flags docs | CONFIRMED docs |
| Google/Gemini deferred | All specs | provider-adapters PLANNED | CONFIRMED boundary |
| Action Contract / human approval | Algorithm §5; Prompt pkg | CLAUDE.md, AGENTS.md | CONFIRMED principles |
| Event topics | Algorithm §6.3 | api-event-contracts.md, events/ | CONFIRMED list / NOT IMPLEMENTED schemas |
| k3s Helm package | k3s spec | deploy/ | Skeleton only |
| Tenant isolation | Algorithm §6.1; k3s | tenancy-model.md | CONFIRMED principles |
| No deploy/push by agents | All specs | Cursor rules, CLAUDE.md, SECURITY.md | CONFIRMED |
| Skills/hooks/agents | Prompt pkg §3,§10–11 | `.claude/**` | Skeleton TODO |
| Deployment profiles | Bootstrap §6 | deployment-profiles.md | CONFIRMED principles |
| Provider interfaces | Bootstrap §5 | packages/provider-adapters READMEs | PROPOSED names |
| Core IDs on contracts | Bootstrap §2 | tenancy-model.md, api-event-contracts.md | Documented; schemas later |
| Prompt files (bootstrap/plan/execution/verification/handoff) | k3s §2 `prompts/`; Prompt pkg §4–9 | `prompts/` 5종 + README (원문 verbatim 사본) | **SCAFFOLDED** (2026-07-12, ADR-0007 D-7) |
| Eval suites (fixtures, trace-graders, policy-tests, regression) | k3s §2 `evals/`; Prompt pkg §12 | `evals/` 4구획 + README | **SCAFFOLDED** — 내용 Wave 3 |
| `forgectl` CLI | k3s §1–2 | none | Wave 2 착수 예정 (합성 F) |
| Multi-host skills (portable/codex/cursor, ponytail-pinned) | k3s §2 `skills/`; Prompt pkg §10 | `.claude/skills/` only (Claude host) | PARTIAL / OPEN DECISION |
| Multi-host hooks (common/codex/cursor) | k3s §2 `hooks/`; Prompt pkg §11 | `.claude/hooks/` only (Claude host) | PARTIAL / OPEN DECISION |
| Contract asyncapi/compatibility subdivisions | k3s §2 `contracts/` | `packages/contracts/` README only | NOT SCAFFOLDED / OPEN DECISION |
| GRS / B-tier remediation·credit owner | Algorithm §0 B계층, §13-7 | none — spec 자체가 미결 선언 | OPEN DECISION (§13 의사결정 주체·일정 확정 선행) |
| 관측 셀·treatment/control 등록 원장 owner | Algorithm §3.7-1; k3s Gate C | ADR-0007 | **확정: experiment-attribution 소유 + audit-ledger hash 앵커링** |
| UsageRecord / per-tenant metering owner | k3s §9.2 Cost 대시보드 | ADR-0007 | **확정: tenant-control 소유** (집행=runner values, 관측=OTel) |
| prompts/·evals/·forgectl/ 보류 승인 주체 | k3s §2 | prompts/·evals/ 스캐폴드 (2026-07-12 사용자 승인); forgectl = Wave 2 | **부분 해소** — 스캐폴드 존재, 내용 구현은 Wave 3 |
| v1 토폴로지 (24 capabilities = 8 Deploy + 10 module + 5 Job + 1 merged; worker host 2) | ADR-0002 rev.3, ADR-0007 rev.2 | service-catalog.md rendering 표 | **CONFIRMED** (2026-07-12, 외부 리뷰 반영) |
| v1 계약 포맷 (JSON Schema/OpenAPI/AsyncAPI, proto 이연) | ADR-0008 (k3s §1 편차 보유) | packages/contracts, events/schemas README | **CONFIRMED** (2026-07-12) |
| 3-context envelope (Tenant/System/Aggregate) | ADR-0006 rev.2 | api-event-contracts.md | **CONFIRMED** (2026-07-12) |
| P0 계약 12종 (context 6종 승격 — 대행사 다고객) | Synthesis rev.2 §7 | packages/contracts README | CONFIRMED 목록 / NOT IMPLEMENTED 스키마 |
| 계약 단위 vs 배포 단위 해석 | k3s §0 vs §11 Gate A | ADR-0002 | accepted (2026-07-12; 모듈 통합만 보류) |
| 승인 전이 권위 경로 | k3s §4.3 | ADR-0003 | accepted (2026-07-12) |
| envelope 필수 ID vs Strategy Card 익명성 | k3s §4.1 vs Algorithm §8.4 | ADR-0006 | accepted 안 A (2026-07-12) — 충돌 해소, events 구현 가능 |

| 언어·monorepo 툴링 (W0) | Synthesis rev.2 §10 W0 | ADR-0009/0010 | accepted (2026-07-12, G1 사전 승인 + critic 검증) |
| 계약 규약·호환성·envelope·tenant·error (W0) | k3s §4.1, Algorithm §8 | ADR-0011~0015 | accepted (2026-07-12, G2 사전 승인 + critic 검증) — envelope 스키마 실물은 W1 |
| telemetry·테스트·CI 규약 (W0) | k3s §6·§9.1, Algorithm §9-10 | ADR-0016~0018 | accepted (2026-07-12) — coverage 90/90/ratchet 사용자 확정 |
| dev-repo 안전 hook·secret·SBOM·devenv (W0) | Prompt pkg §10-11, k3s §5.1 | ADR-0019~0022 | accepted (2026-07-12) — hook 배선은 T13/G3 게이트 |
| worktree 실행 규약 (W0) | Algorithm §9.2, Prompt pkg §7 | ADR-0023 | accepted (2026-07-12) — worktree-ownership.md open 종결 |

| Skill manifest SSOT + validator/quality checker | Prompt pkg §10; wave6-plan §3.1–3.2 | `.claude/skills/manifest.json`, `.claude/skills/manifest.schema.json`, `tools/validation/skill_manifest.py` | **IMPLEMENTED** (2026-07-19, w6-01) — validate-manifest/validate-skills green |
| 16 mandatory SKILL.md | Prompt pkg §10–11; wave6-plan §2 | `.claude/skills/<name>/SKILL.md` ×16 | **IMPLEMENTED** (2026-07-19, w6-02..07) |
| Skill-bundle fail-closed enforcement | wave6-plan §2, §3.1 | `tools/validation/skill_bundle.py`, `tests/unit/skills_bundle/**` | **IMPLEMENTED** (2026-07-19, w6-08) — enforce PASS, no bypass path |
| Plugin / marketplace packaging + drift gate | wave6-plan §1 (w6-09), ADR D-3 | `.claude-plugin/marketplace.json`, `plugins/saena-skill-pack/**`, `tools/validation/skill_pack_sync.py` | **IMPLEMENTED** (2026-07-19, w6-09) — byte-equality drift + `tests/unit/skill_pack` PASS (CI-enforced); `claude plugin validate --strict` PASS on the local macOS run (claude binary absent in CI) |
| New-computer one-command bootstrap | wave6-plan §2 (w6-10) | `scripts/bootstrap-claude.sh` (`--check/--install/--json`), `tests/unit/bootstrap_script/**` | **IMPLEMENTED** (2026-07-19, w6-10) — idempotent, shellcheck-clean |
| saena-pilot CLI + 7 modes (external repo, referenced-not-copied) | wave6-plan §3.3 | `tools/saena-pilot/**`, `tests/unit/pilot/**` | **IMPLEMENTED** (2026-07-19, w6-11) — preflight/audit/plan/implement/verify/resume/status verified |
| Framework discovery adapters (Next/Remix/Astro/Nuxt/SvelteKit/static/unsupported) | wave6-plan §1 (w6-12) | `tools/saena-pilot/src/saena_pilot/discovery/**`, `tests/unit/pilot_discovery/**` | **IMPLEMENTED** (2026-07-19, w6-12) — never-guessed scoring |
| Docker preflight honesty (container-free lanes) | wave6-plan §1 (w6-12), R-4 | `tools/saena-pilot/src/saena_pilot/docker_preflight.py` | **IMPLEMENTED** (2026-07-19, w6-12) — probes and reports truthfully |
| Adversarial security battery (path/symlink/injection/SSRF/secret/no-copy/tamper) | wave6-plan §2 (w6-13) | `tests/security/pilot/**` | **IMPLEMENTED** (2026-07-19, w6-13) |
| Full-lifecycle E2E on synthetic fixtures + resume/failure + RAPID-7-unchanged proof | wave6-plan §2 (w6-14) | `tests/e2e/pilot/**` | **IMPLEMENTED** (2026-07-19, w6-14) |
| Named CI gates (skill-manifest/quality/bundle-bypass, plugin-validate, claude-bootstrap, pilot-*, docs-consistency) | wave6-plan §2, §3.4 (w6-15) | `justfile`, `.github/workflows/ci.yml` (w6-15) | **IMPLEMENTED** (2026-07-19, w6-15) — all 11 named jobs in `.github/workflows/ci.yml` + `justfile` recipes (`just verify-w6`); each exits 0 locally. `plugin-validate` / `claude-bootstrap` guard the claude-binary-dependent steps (absent in CI) behind deterministic enforcing lanes |
| Wave 6 operator runbook (only-tested commands) | wave6-plan §2 (w6-16) | `docs/runbooks/wave6-operator-runbook.md` | **IMPLEMENTED** (2026-07-19, w6-16) — every command block verified by real execution; docs-consistency enforced by the `docs-consistency` CI job (w6-15) |

## Constraints

- Spec originals unchanged
- No fabricated CONFIRMED tech choices

## Open decisions

See design §13 and k3s §12 rows still open.

## Source specification references

- All three `docs/specs/*_v1.md`

## Status

Wave 6 rows IMPLEMENTED (2026-07-19); earlier scaffolding rows remain a
PROPOSED verification matrix.
