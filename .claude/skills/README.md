# .claude/skills/

## Purpose

SAENA skill pack location (Claude host adapter).

## Mandatory skills (from design) — TODO add SKILL.md each

Bootstrap: `saena-intake`, `saena-security-redteam`  
Plan: `saena-site-discovery`, `saena-demand-graph`, `saena-b2b-saas-entity`, `saena-claim-evidence`, `saena-chatgpt-search` ← **엔진 교체점 (ADR-0007)**: v1 hardwire. 2번째 엔진 활성화 시 skill manifest의 이 항목이 엔진별 skill로 분기 — core skill 목록은 불변  
Execute: `saena-technical-aeo`, `saena-answer-capsule`, `saena-schema-fidelity`, `ponytail`  
Verify: `saena-content-fidelity`, `saena-accessibility-visual`, `saena-patch-review`, `saena-rollback`, `ponytail-review`

## Constraints

External plugins only from internal mirror + pinned SHA.

## Status

NOT IMPLEMENTED
