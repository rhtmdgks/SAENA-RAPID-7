"""SAENA FORGE eval harness (w3-10).

`evals/` is a plain directory tree, not a `[tool.uv.workspace]` member (root
`pyproject.toml` is outside this patch unit's exclusive write paths —
`evals/**` / `tests/unit/evals_harness/**` only, per this unit's scope
boundary). `evals/engine/` is nonetheless a regular, dotted-importable
Python package (`evals.engine.*`) — `tests/unit/evals_harness/conftest.py`
makes it importable by inserting the repo root onto `sys.path`, the same
"insert a root directory, import a real package from it" pattern every other
`tests/unit/*/conftest.py` in this repo already uses for not-yet-registered
workspace members (see e.g. `tests/unit/svc_quality_eval/conftest.py`).

See `evals/README.md` for the harness's scope and status.
"""

from __future__ import annotations
