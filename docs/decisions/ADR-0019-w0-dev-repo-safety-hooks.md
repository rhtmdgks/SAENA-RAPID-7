# ADR-0019: W0 dev-repo safety hooks — scope reinterpretation vs W3 FORGE hook ladder

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

implementation-waves.md의 "W3 hooks 5종 실장" 문구와 Wave 0에서 실제로 등록하는 Claude Code hook 5종의 관계를 명문화한다. 두 hook 세트는 이름이 겹치지 않는 서로 다른 층이며, 이 ADR은 그 재해석을 기록한다.

## Scope

In: `.claude/hooks/scripts/`의 dev-repo 안전 hook 5종(이 저장소 자체를 보호), 배선 위치, 실장 순서, 검증·honest-label 절차.
Out: FORGE runtime hook ladder(require_action_contract_for_write, verify_policy_signature, enforce_role_tool_lease 등 prompt pkg §11) — 이는 W3 그대로 유지, 이 ADR이 대체하지 않는다.

## Context

- `.claude/hooks/README.md`는 현재 "설계 문서 (NOT IMPLEMENTED)" 상태이며 prompt pkg §11의 hook 이벤트 목록(SessionStart/PreToolUse/PostToolUse/SubagentStart/before_handoff)을 FORGE 런타임 hook으로 매핑한 것이다. 이는 고객 tenant 실행(runner/orchestrator) 안전장치이며 W3 산출물이다.
- Wave 0가 실제로 필요로 하는 것은 별개 층: **이 monorepo 저장소 자체**를 실수·우회 명령으로부터 지키는 dev-repo hook이다. 대상은 tenant runner가 아니라 Claude Code 세션이 이 저장소에서 여는 Bash/Write/Edit 도구 호출이다.
- 두 층을 같은 "hooks 5종"으로 부르면 implementation-waves.md 문구와 충돌하는 것처럼 보인다 — 사용자 결정 필요 항목(계획 §8-2)으로 등록되어 2026-07-12 확정됨: **W0 = dev-repo 안전 hook 5종, FORGE runtime ladder = W3 그대로**.
- C-1 교훈(security-model.md 제약): "Agent deny = allowlist가 본체 — blacklist 문자열 단독 금지". 단순 blacklist 패턴 매칭은 `git -c http.extraHeader=x push`, `sh -c "git push"`, env 접두 wrapping으로 우회된다.

## Current decision

W0는 dev-repo 안전 hook **5종만** 등록한다. FORGE runtime ladder(prompt pkg §11 전체)는 W3 그대로 유지 — 이 ADR은 그 관계 해석만 담당하며 W3 스코프를 축소하지 않는다.

| # | Hook | 이벤트 | 동작 |
|---|---|---|---|
| 1 | `deny-deploy-push.sh` | PreToolUse/Bash | verb-scoped subcommand allowlist. git: `status/log/diff/show/add/commit/branch/checkout/switch/fetch/stash/worktree` 허용, `push/merge/remote set-url` 등 차단. kubectl/helm: 현재 context가 `k3d-*`일 때만 허용, 아니면 deny. terraform, `gh pr merge`, curl\|sh 계열은 무조건 deny. 정규화 레이어가 `git -c … push`, `sh -c`, env 접두 wrapping을 우회 불가하게 만든다(C-1 준수). |
| 2 | `deny-unpinned-install.sh` | PreToolUse/Bash | 하이브리드: `uv sync --locked`/`uv lock`/`npm ci` allowlist, `uv add`/`pip install`/`npm install <pkg>`는 ask, curl-pipe install은 deny. |
| 3 | `protect-paths.sh` | PreToolUse/Write\|Edit | canonical `tools/validation/policy/protected-paths.txt` 읽어 대상 경로면 `permissionDecision: "ask"` 반환 — 인라인 인간 승인 라우팅(hard deny 아님). |
| 4 | `audit-log.sh` | PostToolUse | `audit/agent-hooks/*.jsonl`에 append(gitignored). secret-redaction 통과 후 기록. 헤더에 "이 로그는 FORGE 불변 audit-ledger가 아니다"를 명시. |
| 5 | `secret-scan.sh` | SessionStart | gitleaks로 staged/uncommitted만 스캔. 전체 이력 스캔은 CI 책임(ADR-0020). |

### 엔지니어링 제약

- deny hook은 fail-closed: 파서 오류 = exit 2(차단).
- protect-paths는 fail-to-ask: 오류 시에도 인간 승인 경로로 유도.
- POSIX sh만(macOS bash 3.2 호환), jq/네트워크 접근 금지, 실행 100ms 미만.
- `.claude/hooks/DISABLED` 파일 존재 시 전 hook 즉시 no-op(무중단 rollback) — 이 사용 자체를 audit line에 기록.

### 배선과 honest-label 절차

- 배선은 체크인 `.claude/settings.json`(팀 공용, 버전 관리)에 `.claude/settings.example.json`의 deny 17규칙을 승격하는 형태 — **보호 경로**, 실제 diff는 별도 인간 승인 게이트(G3)를 거친다.
- `.claude/hooks/README.md`·CLAUDE.md의 Status는 "NOT IMPLEMENTED"에서 검증 증거 3종(unit corpus green + sandbox bare-repo push 차단 증명 + `claude --debug` hook 등록 로그)이 **같은 커밋**에 함께 있을 때만 플립한다. 그 전에 "hook 활성" 주장 금지.

## Constraints

- FORGE runtime ladder(§11 전체 항목)는 W3에서 원안대로 실장 — 이 ADR로 항목이 줄거나 대체되지 않는다.
- dev-repo hook은 단일 방어선일 뿐 — 최종 통제는 branch protection + W2A policy-gate(security-model.md).
- protected-paths canonical list는 hook + CI symmetry check + CODEOWNERS 3중 소비 — drift는 CI fail.

## Open decisions

- hook 파서 우회 잔존 위험(base64, xargs, 스크립트 경유) — 완화는 branch protection + W2A policy-gate로 승계.

## Source specification references

- `.claude/hooks/README.md` (C-1 allowlist-first 원칙, 설계-only 현재 상태)
- `docs/architecture/implementation-waves.md` W3 "hooks 5종 실장"
- `docs/architecture/security-model.md` 제약 (allowlist가 본체 — C-1)
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §11 (Required hook checks)
- CLAUDE.md Protected paths

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.
