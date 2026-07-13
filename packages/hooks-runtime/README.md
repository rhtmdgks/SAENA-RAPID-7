# packages/hooks-runtime

## Purpose

`saena_hooks_runtime` — the FORGE **runtime** hook ladder (w3-06, Wave 3).
This is the pure decision engine for the 5 agent-runtime hooks named in
`docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §11 ("Required
hook checks"): `session_start`, `pre_tool_use`, `post_tool_use`,
`subagent_start`, `before_handoff`.

**This is a different layer from `.claude/hooks/`.** `.claude/hooks/` (ADR-0019,
W0) is dev-repo safety wiring for THIS repository's own Claude Code
sessions — shell scripts, wired into `.claude/settings.json`, protecting
this repo's own git history/branch policy. `saena_hooks_runtime` is the
FORGE **agent-runner execution runtime** hook ladder for CUSTOMER repos
under Wave 3 — a Python decision engine, not wired into anything in this
repo, with its own Action Contract / tenant / patch-unit model. CLAUDE.md's
own "Status" line ("FORGE runtime hook ladder는 W3 NOT IMPLEMENTED") is
what this patch unit resolves — a follow-up patch unit should update that
line once this package is Integrator-wired.

## Scope

In (this patch unit, w3-06):
- `saena_hooks_runtime.hooks.{session_start,pre_tool_use,post_tool_use,subagent_start,before_handoff}`
  — one pure function per hook, each taking a frozen-dataclass typed input
  and returning a typed `HookDecision`.
- `saena_hooks_runtime.contract` — the `ActionContract`/`PatchUnit` model +
  `compute_contract_hash`/`validate_contract`.
- `saena_hooks_runtime.command_normalize` — the wrapper-defeating command
  normalization layer for `pre_tool_use`.
- `saena_hooks_runtime.rules.*` — segment-level policy matchers
  (`deploy_push`, `unpinned_install`, `egress`, `write_scope`).
- `saena_hooks_runtime.paths` — path normalization + glob scope matching.
- `saena_hooks_runtime.redact` — secret/PII redaction for detail/audit text.
- `saena_hooks_runtime.ports`/`fakes` — the `AuditSink` Protocol + in-memory
  fakes.
- `tests/unit/hooks_runtime/corpus/manifest.json` — the bypass corpus (55
  fixtures, 32 DENY / 23 ALLOW, one wrapper-defeat category per named bypass
  form).

Out (explicitly NOT this patch unit's scope — see "Integrator action
needed" below):
- Wiring this engine into an actual runner (subprocess/HTTP hook
  invocation, a real `AuditSink` adapter, a real secret scanner, a real git
  worktree/policy-signature check). Every effectful concern is modeled as
  either a plain-data field on a typed input (secret-scan RESULTS, dirty-worktree
  flag, policy-signature-valid flag) or, for the one hook whose own decision
  depends on an effectful call succeeding (`post_tool_use.append_audit_event`),
  a `typing.Protocol` port with in-memory fakes for tests. See each hook
  module's docstring for the specific rationale.
- `uv` workspace registration (packaging note below).
- Updating CLAUDE.md's "Status" line / any `.claude/hooks/README.md`
  content (out of this patch unit's exclusive write paths).

## Packaging note

This package is **deliberately NOT a `uv` workspace member** — the same
precedent `tools/forgectl` set at w2-19/w2-20 (see
`tools/forgectl/README.md`'s own "Packaging note" and
`tools/forgectl/pyproject.toml`'s trailing comment). Registering it (root
`pyproject.toml` `[tool.uv.workspace]` members + `[tool.uv.sources]` + a
dev-group dependency entry, `[tool.mypy]` `files`, `[tool.coverage.run]`
`source`, `.importlinter` `root_packages` + a leaf/boundary contract) all
require editing root config files, which sit outside this patch unit's
exclusive write paths (`packages/hooks-runtime/**`,
`tests/unit/hooks_runtime/**` only, per the team-lead assignment). That
registration is Integrator/Wave-3-exit work.

In the meantime, `tests/unit/hooks_runtime/conftest.py` inserts
`packages/hooks-runtime/src` onto `sys.path` directly (the same pattern
`tests/unit/forgectl/conftest.py` uses) so the test suite runs correctly
without workspace membership — `uv run pytest tests/unit/hooks_runtime -q`
works today, unregistered.

## Verified

```
uv run pytest tests/unit/hooks_runtime -q
# 172 passed

uv run ruff check packages/hooks-runtime tests/unit/hooks_runtime
uv run ruff format --check packages/hooks-runtime tests/unit/hooks_runtime
# All checks passed! / N files already formatted

uv run mypy packages/hooks-runtime/src
# Success: no issues found in 20 source files
# (also verified with --strict — same result)

uv run pytest -q -m "not integration"
# 2457 passed, 26 skipped, 171 deselected — full unit lane still green,
# this patch unit's conftest.py does not break test collection elsewhere.
```

## Design interpretation notes

The B-department prompt package v1 §11 table and the team-lead task
instructions name every hook's check functions and its "Blocks:" list, but
leave some operational detail to the implementing patch unit. Where a
judgment call was made, it is documented in the relevant module's own
docstring; the two most consequential ones are repeated here for
visibility:

1. **`ActionContract` gets one field beyond the task instructions' named
   set**: `approved_egress_domains` is threaded through
   `PreToolUseInput` (NOT `ActionContract` itself, per instructions) as a
   separate parameter, since `deny_unapproved_network_egress` needs an
   allowlist to check against and the task instructions' `ActionContract`
   field list does not name one. Default-deny: an empty
   `approved_egress_domains` (the default) denies every non-loopback
   network call.

2. **`subagent_start`'s "deny network for browser jobs"** is read as "deny
   UNSCOPED network for browser jobs", not "browser subagents may never
   have network at all" (which would make a `browser` role pointless — its
   entire job is fetching pages). `ToolLease.network_targets` is the scope
   list; `network=True` with an EMPTY `network_targets` is what gets denied
   (`BROWSER_UNSCOPED_NETWORK`). See `hooks/subagent_start.py`'s module
   docstring for the full reasoning and the alternative readings
   considered.

## Known limitations (documented, not silently absorbed)

- `command_normalize.py` is intentionally not a full POSIX shell parser —
  it defeats the specific bypass corpus this patch unit was asked to
  defeat (see that module's docstring), not arbitrary shell syntax.
  Extending it for a new wrapper form discovered later is expected,
  ordinary future work, not a design flaw to work around.
- `rules/deploy_push.py`'s DNS/robots.txt-live-mutation and CMS-publish
  matchers are heuristic pattern tables (`aws route53`, `gcloud dns`, `az
  dns`, `wp`/`contentful`/`sanity`/`strapi`/`ghost`/`netlify-cms`/`directus`
  publish verbs), not an exhaustive vendor CLI catalog.
- `rules/unpinned_install.py` covers pip/pip3, `uv add`/`uv pip install`,
  npm/yarn/pnpm, gem, and `go install ...@latest` — not every package
  manager in existence.
- `rules/egress.py`'s host extraction is best-effort string/URL parsing,
  not a real shell-argument-aware network-call analyzer.

## Integrator action needed

1. **`uv` workspace registration** — see "Packaging note" above.
2. **`.importlinter` contract suggestion** (not applied here, outside this
   unit's exclusive write paths): add `saena_hooks_runtime` to
   `root_packages`, with a leaf/boundary contract mirroring
   `saena_forgectl`'s — this package currently has ZERO internal `saena_*`
   dependencies (stdlib only), so the simplest correct contract is "must
   not be imported by `saena_domain` or any service, and must not import
   `saena_domain` or any service" (a standalone engine, like
   `saena_forgectl`, not a shared library other packages depend on).
3. **Real adapter wiring** — a real `AuditSink` (audit-ledger-service or
   equivalent), a real secret scanner producing `SecretFinding` values, a
   real git-worktree-dirty check, a real policy-bundle-signature verifier,
   and the actual Claude Code / Codex / Cursor hook-event -> this engine's
   typed-input translation layer, per §10's "Host adapter implementation
   map".
4. **CLAUDE.md status line** — once wired, CLAUDE.md's "FORGE runtime hook
   ladder는 W3 NOT IMPLEMENTED" line should be updated (that file is
   outside this unit's exclusive write paths).

## Source specification references

- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §11
  ("Required hook checks") — the authoritative hook/check list this
  package implements.
- CLAUDE.md — "Engine scope (v1)" (ChatGPT Search only,
  `contract.REQUIRED_ENGINE_SCOPE`), principle 3 ("인간 승인 전 write
  금지"), principle 10 ("배포·push·merge 금지"), principle 12 ("Untrusted
  content").
- ADR-0019 — names this exact package/layer distinction ("FORGE runtime
  hook ladder(action contract·policy signature·role lease)는 여전히 W3
  미구현").
- `tools/forgectl/README.md`/`pyproject.toml` — the non-workspace-member
  packaging precedent this package follows.
