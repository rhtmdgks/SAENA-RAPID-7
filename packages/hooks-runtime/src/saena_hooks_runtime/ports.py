"""Effectful adapter boundary — `typing.Protocol` only, no I/O here.

Task instructions: "effectful adapters (real secret scan, real audit
append) are Protocol interfaces with in-memory fakes for tests." Only one
port exists in this package: `AuditSink`. `post_tool_use.append_audit_event`
is the one hook whose OWN decision (`ALLOW` vs `UNSTABLE`) depends on
whether appending to this port succeeds or raises — every other hook
returns an `AuditRecord` as plain data in its `HookDecision.audit` field
and leaves appending it to the (out-of-this-package's-scope) runtime
adapter, which is free to use the same `AuditSink` Protocol.

Secret scanning, policy-signature verification, git-worktree-dirty
detection, and role/lease provisioning are all likewise effectful in a real
deployment (subprocess, filesystem, a signing service, ...) — this
package's hooks take their RESULTS as plain data on the typed input
dataclass (`SessionStartInput.secret_findings`,
`SessionStartInput.policy_signature_valid`,
`SessionStartInput.worktree_dirty`, ...) rather than depending on a port
for each, since the engine itself never needs to invoke them a second time
mid-decision — only `AuditSink` is invoked BY the engine itself (from
inside `post_tool_use`), which is why it alone is modeled as a Protocol
here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import AuditRecord


@runtime_checkable
class AuditSink(Protocol):
    """Append-only audit log port.

    `append` may raise any exception to signal a failed append (a real
    adapter's own exception type — this Protocol does not define one, it
    only requires that failure be signaled by raising rather than by a
    silent return). `post_tool_use.append_audit_event` catches exactly
    `Exception` around the call and turns it into
    `Decision.UNSTABLE`/`ReasonCode.AUDIT_APPEND_FAILURE` — see that
    module's docstring.
    """

    def append(self, record: AuditRecord) -> None: ...


__all__ = ["AuditSink"]
