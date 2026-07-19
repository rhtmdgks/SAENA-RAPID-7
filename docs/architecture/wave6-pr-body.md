# Wave 6 — Pilot Operationalization · Skill Distribution · External-Project Runner

Base `main`: `68b63a2d6eb662ee7fcc51432e5eb9b5a14e6ea1`. Branch:
`wave6-operationalization`. Engine scope unchanged: **ChatGPT Search only**.
No merge, no deploy, no push beyond this branch, no force-push, no tag/release.

## What shipped (3 outcomes)

1. **SAENA Claude Code Skill Pack** — all 16 mandatory `SKILL.md` files under
   `.claude/skills/` (Bootstrap 2, Plan 5, Execute 4 incl. `ponytail`, Verify 5
   incl. `ponytail-review`), each substantive (150–330 lines, 16 required
   sections, deterministic ≥8-step workflows, engine-scope + enforcement-honesty
   notes). Backed by a machine-validated SSOT manifest
   (`.claude/skills/manifest.json` + `manifest.schema.json`), a validator
   (`tools/validation/skill_manifest.py`, 55 tests), fail-closed bundle
   enforcement (`tools/validation/skill_bundle.py`, 54 tests, no bypass path),
   and a Claude Code plugin + marketplace (`plugins/saena-skill-pack/` +
   `.claude-plugin/marketplace.json`) that passes `claude plugin validate
   --strict` with a byte-equality drift gate (`skill_pack_sync.py`, 33 tests).
2. **One-command new-computer bootstrap** — `scripts/bootstrap-claude.sh`
   (`--check/--install/--json`, idempotent, POSIX sh, shellcheck-clean, safe when
   sourced, spaces+Unicode paths, honest N/A for optional deps, no secret
   output; corpus + 24 unit tests).
3. **External customer-project pilot launcher** — `tools/saena-pilot/` (workspace
   member, `uv run saena-pilot`), 7 modes (preflight/audit/plan/implement/verify/
   resume/status), references an external customer repo via `claude --add-dir`
   **without copying it into RAPID-7**, writes customer source only inside a
   dedicated `saena-pilot/<run-id>` worktree, fail-closed intake/action contract,
   tamper-evident evidence chain bound to RAPID-7 SHA + customer SHA + domain +
   mode + run-id + manifest version + skill-bundle fingerprint, framework
   discovery adapters (Next/Remix/Astro/Nuxt/SvelteKit/static/unsupported), and
   an honest Docker preflight.

## Verification

- `just verify` green, deterministic (repeated runs). Whole-tree unit lane:
  6070 passed / 45 skipped (baseline 5363 + 707 Wave 6).
- 11 named CI gates in `.github/workflows/ci.yml` (`just verify-w6` locally):
  skill-manifest, skill-quality, skill-bundle-bypass, plugin-validate,
  claude-bootstrap, pilot-path-boundary, pilot-security, pilot-e2e,
  pilot-failure-modes, pilot-evidence-integrity, docs-consistency — each exits 0
  locally.
- E2E lane: 57 tests, armed completeness guard (partial `-k` selection → exit 4).
- Security battery: 147 tests. Integrator hardened 2 real vulns the battery
  found (numeric-IP SSRF in `domain.py`; modern secret shapes `sk-proj-`/
  `github_pat_`/`glpat-` in `secretguard.py`) + surfaced `.claude/hooks/DISABLED`.
- Secret scan: pinned gitleaks 8.30.0 over full history → "no leaks found"
  (8 fabricated test-fixture shapes fingerprinted in `.gitleaksignore` per
  ADR-0020, no path allowlist).
- Independent critics (non-authors): skill-semantics PASS; docs-truthfulness
  CONDITIONAL_PASS → 1 MUST-FIX applied; security = Lead-fallback re-verification
  (independent critic hit a session limit) + the 147-test battery.

## Not done (human-gated)

Merge to main, production deploy, live customer observation, ChatGPT observation
account/ToS/legal, and PR review — all remain human decisions. The pilot never
deploys or pushes customer work.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
