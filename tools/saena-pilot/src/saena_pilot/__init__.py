"""`saena_pilot` — SAENA external-customer-project pilot launcher (w6-11).

Frozen contract: docs/architecture/wave6-plan.md §3.3. The pilot references
an external customer repository (never copies it), validates boundaries
fail-closed, enforces the skill bundle at every start, records tamper-evident
evidence outside both repositories, and launches Claude Code from the RAPID-7
root with `--add-dir` (customer root for read modes, a dedicated customer-side
worktree for `implement`).
"""

from __future__ import annotations

__version__ = "0.1.0"
