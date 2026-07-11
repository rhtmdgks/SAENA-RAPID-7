# .claude/hooks/

## Purpose

SAENA FORGE 안전 게이트의 Claude Code hook 설계 + 설정 예시. Prompt pkg §11 hook 목록 + design §10 policy-as-code를 Claude Code hook 이벤트로 매핑.

## Status

**설계 문서 (NOT IMPLEMENTED).** 이 디렉토리에 **활성 hook 스크립트·배선은 없다.** 아래는 설계와 예시이며, 실제로 동작하지 않는다. Hook은 완전한 보안 경계도 아니다 — 최종 통제는 Forge Policy Gate + k3s(namespace·NetworkPolicy·non-root·short-lived credential·branch protection). 정직 표기 원칙: "hook 활성" 주장 금지.

## Hook 이벤트 매핑 (설계 — Prompt pkg §11)

| Claude Code 이벤트 | 강제 정책 | 차단 예시 |
|---|---|---|
| SessionStart | verify_run_context, verify_policy_signature, secret_scan | contract 없는 write session |
| PreToolUse | require_action_contract_for_write, deny_out_of_scope_write, deny_deploy_push_cms_dns, deny_unapproved_egress, deny_unpinned_install | `git -c … push`, `kubectl patch`, `helm upgrade`, production token, unpinned install (allowlist가 본체 — blacklist 단독 금지, C-1) |
| PostToolUse | record_changed_file_and_patch_unit, append_audit_event, mark_required_tests_dirty | contract 밖 파일 수정 감지 |
| SubagentStart | enforce_role_tool_lease, inject_untrusted_content_policy | critic에게 write lease |
| Stop / before_handoff | run_quality_matrix, require_independent_critic, require_rollback_manifest | "완료" 오판, rollback 없는 patch |

## 설정 예시 (EXAMPLE ONLY — 미배선)

아래는 `settings.json`에 넣을 수 있는 hook 배선의 **형태 예시**다. 실제 스크립트(`scripts/…`)는 이 저장소에 없으며, 넣기 전 Security + Lead 승인 필요.

```jsonc
// settings.local.json (EXAMPLE — 복사·검토 후에만. 스크립트 부재 시 무동작)
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/scripts/deny-deploy-push.sh" }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/scripts/require-action-contract.sh" }
        ]
      }
    ],
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": ".claude/hooks/scripts/secret-scan.sh" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": ".claude/hooks/scripts/require-rollback-manifest.sh" } ] }
    ]
  }
}
```

주의: 위 `scripts/*.sh`는 **존재하지 않는다**. 배선만 하고 스크립트가 없으면 게이트는 무동작 — "hook으로 차단됨"이라 표현하지 말 것. 구현은 Wave 3 (implementation-waves.md).

## 다층 방어 (hook은 1겹일 뿐)

hook 밖 강제: Kubernetes namespace 격리, non-root runner, default-deny NetworkPolicy, short-lived credential, Git branch protection, immutable audit storage (Prompt pkg §11 하단). 승인 권위 경로는 ADR-0003 (Policy Gate 선행 → Temporal signal).

## Source specification references

- Prompt pkg §10–11; Algorithm §10; k3s §6; ADR-0003; security-model.md
