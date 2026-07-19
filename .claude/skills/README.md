# .claude/skills/

## Purpose

SAENA skill pack location (Claude host adapter). The 16 mandatory FORGE skills
are delivered as `SKILL.md` files, registered in a machine-validated manifest,
and packaged as the `saena-skill-pack` plugin.

## Delivered skills (16 SKILL.md) — IMPLEMENTED

SSOT: [`manifest.json`](manifest.json) (`saena.skill-manifest/v1`,
`bundle_name: saena-forge-core`, `engine_scope: ["chatgpt-search"]`). Each skill
lives at `<name>/SKILL.md`:

Bootstrap: `saena-intake`, `saena-security-redteam`  
Plan: `saena-site-discovery`, `saena-demand-graph`, `saena-b2b-saas-entity`, `saena-claim-evidence`, `saena-chatgpt-search` ← **엔진 교체점 (ADR-0007)**: v1 hardwire. 2번째 엔진 활성화 시 skill manifest의 이 항목이 엔진별 skill로 분기 — core skill 목록은 불변 (`adr0007_engine_swap_point: true`)  
Execute: `saena-technical-aeo`, `saena-answer-capsule`, `saena-schema-fidelity`, `ponytail`  
Verify: `saena-content-fidelity`, `saena-accessibility-visual`, `saena-patch-review`, `saena-rollback`, `ponytail-review`

## Enforcement (gates)

- **skill-manifest** — `tools/validation/skill_manifest.py`
  (`validate-manifest` structural/semantic; `validate-skills` both-direction
  disk↔manifest cross-check).
- **skill-quality** — `validate-skills` also enforces the SKILL.md contract
  (required H2 sections, non-trivial content, frontmatter agreement).
- **skill-bundle** — `tools/validation/skill_bundle.py enforce` (fail-closed
  full-bundle enforcement; consulted at every `saena-pilot` start).
- **plugin sync/drift** — `tools/validation/skill_pack_sync.py check`
  (byte-equality between `.claude/skills/**` and the generated
  `plugins/saena-skill-pack/` copy).

## Constraints

External plugins only from internal mirror + pinned SHA.

Enforcement honesty: the FORGE **runtime** hook ladder is still NOT IMPLEMENTED
(Wave 3). Skills *declare* their safety/verification gates; the W0 dev-repo
hooks + human review enforce today.

## Status

IMPLEMENTED (2026-07-19) — 16 SKILL.md delivered, manifest SSOT + skill-manifest
/ skill-quality / skill-bundle / plugin-sync validators green; packaged as the
`saena-skill-pack` plugin (`.claude-plugin/marketplace.json`). Wave 6 (w6-01..09).
