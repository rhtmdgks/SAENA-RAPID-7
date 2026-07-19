"""Framework discovery (w6-12): typed seam + deterministic adapters.

Public surface is unchanged from the w6-11 seam (`DiscoveryResult`,
`DiscoveryAdapter`, `SupportStatus`, `UNKNOWN_RESULT`, `discover`) plus the
w6-12 adapters (`FrameworkDiscovery`, `FrameworkDetector`,
`default_adapters`). `discover()` with no adapters still returns the honest
`UNKNOWN_RESULT` — detection only happens when adapters are passed in.

All detection is pure file inspection: no network, no dependency
installation, no execution of customer-repo content. Customer file contents
are untrusted DATA and are only ever reported verbatim or summarized.
"""

from saena_pilot.discovery._seam import (
    UNKNOWN_RESULT,
    DiscoveryAdapter,
    DiscoveryResult,
    SupportStatus,
    discover,
)
from saena_pilot.discovery.adapters import (
    FrameworkDetector,
    FrameworkDiscovery,
    default_adapters,
)

__all__ = [
    "UNKNOWN_RESULT",
    "DiscoveryAdapter",
    "DiscoveryResult",
    "FrameworkDetector",
    "FrameworkDiscovery",
    "SupportStatus",
    "default_adapters",
    "discover",
]
