"""The 5 FORGE runtime hooks (B-department prompt package v1 §11)."""

from __future__ import annotations

from .before_handoff import BeforeHandoffInput, before_handoff
from .post_tool_use import PostToolUseInput, post_tool_use
from .pre_tool_use import PreToolUseInput, pre_tool_use
from .session_start import SessionStartInput, session_start
from .subagent_start import SubagentStartInput, subagent_start

__all__ = [
    "BeforeHandoffInput",
    "PostToolUseInput",
    "PreToolUseInput",
    "SessionStartInput",
    "SubagentStartInput",
    "before_handoff",
    "post_tool_use",
    "pre_tool_use",
    "session_start",
    "subagent_start",
]
