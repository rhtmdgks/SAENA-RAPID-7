"""Temporal Activities for `ExecutionWorkflow`.

`run_execution_activity` is a STUB (task instruction: "real execution = W3").
It only demonstrates the heartbeat contract this Activity type commits to
(timeouts.py) and the blob-single-gateway discipline (module docstring below)
— it does not run any real agent/runner work in this patch unit.

Blob single-gateway note (task instruction 3): this Activity, and this whole
package, never talks to blob storage directly. Artifacts are referenced only
by an opaque `manifest_ref` string (see `ExecutionActivityInput` below) —
resolving that ref to actual bytes is artifact-registry-service's job
(the "blob 단일 관문" from the W2B exit gate), strictly out of this patch
unit's exclusive-write scope and out of this Activity's responsibility. If a
future revision of this stub needs to read/write artifact bytes, it MUST do
so through artifact-registry-service's published contract, never a direct
object-store client constructed in this package.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from temporalio import activity

from saena_orchestrator.timeouts import HEARTBEAT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class ExecutionActivityInput:
    """Activity input — artifacts referenced by manifest ref only (blob
    single-gateway note above), never a direct blob key/URL.
    """

    contract_hash: str
    manifest_ref: str


@dataclass(frozen=True, slots=True)
class ExecutionActivityResult:
    """Stub result — W3 will replace this with real execution output."""

    contract_hash: str
    accepted: bool


@activity.defn
async def run_execution_activity(
    activity_input: ExecutionActivityInput,
) -> ExecutionActivityResult:
    """Stub execution Activity — heartbeats on the configured cadence so a
    real long-running implementation (W3) can drop in behind this signature
    without changing the workflow's `execute_activity` call shape.

    Heartbeats once here to prove the heartbeat contract is live end-to-end
    (a Worker with no heartbeat call at all would silently rely on
    `heartbeat_timeout` never being exercised) — a real W3 implementation
    will heartbeat repeatedly across its actual long-running work.
    """
    activity.heartbeat("run_execution_activity: accepted", activity_input.contract_hash)
    # Stub only: no real work. The `asyncio.sleep(0)` yields control once so
    # this remains a well-behaved async Activity even though it does nothing
    # (Temporal Activities must be async-friendly / cooperative).
    await asyncio.sleep(0)
    return ExecutionActivityResult(contract_hash=activity_input.contract_hash, accepted=True)


__all__ = [
    "ExecutionActivityInput",
    "ExecutionActivityResult",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "run_execution_activity",
]
