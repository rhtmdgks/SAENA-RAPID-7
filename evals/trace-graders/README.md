# evals/trace-graders

See ../README.md. Scaffold approved 2026-07-12 (ADR-0007 D-7).

## w3-10 (2026-07-13) note on physical location

This directory's documented purpose ("agent run trace 채점기") is
implemented, but the actual scorer CODE lives under `evals/engine/scorers/`,
not here: this directory's name is hyphenated (`trace-graders`), which
cannot be a Python dotted-import path (`import evals.trace-graders` is a
syntax error) — every other implemented service/package directory in this
repo with a hyphenated name (e.g. `services/platform/quality-eval-service/`)
holds its real importable code under a `src/<underscored_package_name>/`
subdirectory for exactly this reason. `evals/engine/` is that underscored,
importable home for this unit's harness engine + all 9 axis scorers; this
`trace-graders/` directory is kept as the scaffold's documented concept
anchor (and this note), per this patch unit's scope (`evals/**` only —
renaming the scaffolded directory tree itself was out of scope).

See `evals/README.md`'s "w3-10 구현" table for the 9 axes and
`evals/engine/scorers/__init__.py` for the scorer registry.
