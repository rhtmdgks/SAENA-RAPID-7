"""Typed discovery seam (moved verbatim from ``discovery/__init__`` in w6-12
so adapter modules can import it without a circular import).

The contract is unchanged from w6-11: the default `discover()` is honest about
what it knows — it returns `UNKNOWN` unless an adapter positively identifies
the repo. No adapter may guess: a result is either a positive detection or
`UNKNOWN`/`UNSUPPORTED`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Outcome of framework discovery over the customer root."""

    framework: str
    status: SupportStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "status": self.status.value,
            "detail": self.detail,
        }


class DiscoveryAdapter(Protocol):
    """One framework detector. Returns a positive `DiscoveryResult` or `None`
    when this adapter cannot identify the repo."""

    def detect(self, customer_root: Path) -> DiscoveryResult | None: ...


#: Honest default when no adapter matches (or none were supplied).
UNKNOWN_RESULT = DiscoveryResult(
    framework="unknown",
    status=SupportStatus.UNKNOWN,
    detail=(
        "no discovery adapters were supplied for this call — no detection was "
        "attempted (pass saena_pilot.discovery.default_adapters())"
    ),
)


def discover(customer_root: Path, adapters: Sequence[DiscoveryAdapter] = ()) -> DiscoveryResult:
    """Run adapters in order; first positive detection wins, else UNKNOWN."""
    for adapter in adapters:
        result = adapter.detect(customer_root)
        if result is not None:
            return result
    return UNKNOWN_RESULT
