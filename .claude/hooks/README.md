# .claude/hooks/

## Purpose

Lifecycle hooks skeleton. Runtime enforcement still requires Forge Policy Gate + k3s.

## Required checks (from spec) — TODO implement

- session_start: verify_run_context, verify_policy_signature, secret_scan
- pre_tool_use: deny out-of-scope write, deny deploy/push/CMS/DNS, deny unapproved egress, deny unpinned install, require Action Contract for write
- post_tool_use: record changed files, audit event, mark tests dirty
- subagent_start: role tool lease, untrusted content policy
- before_handoff: quality matrix, independent critic, rollback manifest

## Status

NOT IMPLEMENTED
