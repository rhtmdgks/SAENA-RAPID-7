# evals/policy-tests

See ../README.md. Scaffold approved 2026-07-12 (ADR-0007 D-7).

## w3-10 (2026-07-13) — IMPLEMENTED

`forbidden_action/` — the mission's axis 8 fixtures (deny/allow policy
bundle regression cases): git push / kubectl mutate / curl-pipe-to-shell /
`google-gemini` engine denial, plus their `false_positive_guard`
(`git commit -m "push to prod later"` must ALLOW) and `false_negative_guard`
(a near-miss `engine_id` must still DENY) discrimination fixtures.

Scored by `evals/engine/scorers/forbidden_action.py` over the REAL
`saena_hooks_runtime.rules.deploy_push.matches_deploy_push_cms_dns` +
`saena_hooks_runtime.command_normalize.has_pipe_to_interpreter` +
`saena_schemas.common.engine_id_v1.EngineId` (v1 closed engine enum). Run
by `tests/unit/evals_harness/test_all_axes.py` (CI-blocking, unit lane).
