"""In-memory `AuditSink` fakes — task instructions: "effectful adapters
... are Protocol interfaces with in-memory fakes for tests."

Shipped in the package proper (not only under `tests/`) so both this
package's own test suite and any future Integrator-side wiring code can
reuse the same fakes rather than each hand-rolling one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import AuditRecord


@dataclass(slots=True)
class InMemoryAuditSink:
    """Records every appended `AuditRecord`, in order. Never raises."""

    records: list[AuditRecord] = field(default_factory=list)

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


@dataclass(slots=True)
class FailingAuditSink:
    """Raises `RuntimeError` on every `append` call — used to exercise the
    `post_tool_use` "audit append failure ⇒ run marked unstable" path."""

    message: str = "simulated audit append failure"

    def append(self, record: AuditRecord) -> None:
        raise RuntimeError(self.message)


__all__ = ["FailingAuditSink", "InMemoryAuditSink"]
