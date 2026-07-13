"""saena_hooks_runtime — the SAENA FORGE runtime hook ladder (w3-06).

Pure decision engine for the 5 agent-runtime hooks named in
`docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §11:
`session_start`, `pre_tool_use`, `post_tool_use`, `subagent_start`,
`before_handoff`. See `hooks/` for each hook's function + typed input, and
this package's README.md for scope, packaging status, and Integrator
follow-up.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
