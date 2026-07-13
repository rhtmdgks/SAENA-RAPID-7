# tests/security

## Purpose

failure-mode 9종 (k3s spec §10) ↔ fixture ↔ test 1:1 매핑 + rollback
verification gate (testing-strategy.md sec F-7/F-8). Every test here wires
directly against REAL W3 job/hook/domain code — no mocked-out domain logic.

## Scope

Pure, deterministic checks only (no real external process/container/network
I/O). Container/Temporal-backed rollback proofs live under
`tests/integration/failure_modes/`.

## Current decision

IMPLEMENTED (w3-09). Authoritative matrix: `failure_mode_matrix.json` (+
`test_failure_mode_matrix.py`, the CI-blocking completeness gate — fails if
any of the 9 modes loses its fixture/test, or if a referenced test function
is renamed/deleted without updating the matrix).

- `test_f1_prompt_injection.py` … `test_f9_measurement_fraud.py` — one
  module per failure mode (`F-1`..`F-9`), each wired against the real
  package/service the mission maps that mode to (`saena_hooks_runtime`,
  `saena_quality_eval`, `saena_agent_runner`, `saena_repository_intake`).
- `measurement_fraud.py` — a minimal, deterministic B-layer success
  evaluator for `F-9`; **no service in this repo owns this yet** (see that
  module's own docstring) — report this gap, do not treat it as final.
- `test_rollback_*.py` — the rollback verification gate's pure/deterministic
  half: no-partial-commit, failed-worktree cleanup, audit-chain
  preservation, approval-ledger immutability, artifact immutability,
  idempotency/outbox replay dedup, tenant isolation on rollback, and a REAL
  temp `git` repo proving the main/source repo is byte-identical after a
  denied-and-rolled-back attempt.

## Constraints

- No fake green by deleting assertions
- No `sys.path`/import coupling into this suite's OWN exclusive-write test
  code from outside it — only READ-only reuse of sibling `tests/unit/**`
  factory-helper modules (never their `conftest.py`), same precedent as
  `tests/integration/orchestrator/conftest.py`.

## Open decisions

- `F-5` (skill compromise) and `F-9` (measurement fraud) are wired against
  the closest REAL existing mechanism / a provisional evaluator this patch
  unit built, because no dedicated `skill_bundle_hash` validator or
  `experiment-attribution-service` B-layer gate exists in this repo yet —
  see each mode's `missing_owner_note` in `failure_mode_matrix.json`. Not a
  silent decision: flagged to main for a future owning unit.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §10
- `docs/architecture/testing-strategy.md` sec F-7/F-8

## Status

IMPLEMENTED (w3-09) — `uv run pytest tests/security -q` green.
