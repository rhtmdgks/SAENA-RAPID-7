"""Default-deny NetworkPolicy check (k3s spec §8.1 condition 4: "default-deny
NetworkPolicy is absent").

Values shape (k3s spec §6.2 + §7 skeleton):

```yaml
global:
  network:
    defaultDeny: true
networkPolicy:
  defaultDeny: true
  runner:
    ingress: []
    egress: [internal-policy-gate, internal-artifact-registry, ...]
  browser:
    egress: [approved-observation-hosts, ...]
    denied: [git-write, kubernetes-api, cloud-metadata]
```

The spec's §7 skeleton and §6.2 detail block both declare a `defaultDeny`
flag (`global.network.defaultDeny` and `networkPolicy.defaultDeny`
respectively) — this check accepts either location as satisfying the
requirement (a values file only needs to declare it once), but requires at
least one of them to be explicitly `true`.

Static-preflight scope note: this check verifies the values file
*declares* `defaultDeny: true` — it does not query a live cluster to
confirm a matching `NetworkPolicy` object actually exists and is enforced
(live-cluster extension, out of scope for W2A).
"""

from __future__ import annotations

from typing import Any

from saena_forgectl.checks._util import get_path
from saena_forgectl.models import CheckResult

CHECK_NAME = "network_policy"


def check_network_policy(values: dict[str, Any]) -> CheckResult:
    """Fail iff neither `global.network.defaultDeny` nor
    `networkPolicy.defaultDeny` is declared `true`."""
    global_default_deny = get_path(values, "global", "network", "defaultDeny")
    top_level_default_deny = get_path(values, "networkPolicy", "defaultDeny")

    if global_default_deny is True or top_level_default_deny is True:
        return CheckResult(
            name=CHECK_NAME,
            passed=True,
            detail="default-deny NetworkPolicy is declared",
            context={
                "global.network.defaultDeny": global_default_deny,
                "networkPolicy.defaultDeny": top_level_default_deny,
            },
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=False,
        detail=(
            "default-deny NetworkPolicy is absent — neither "
            "global.network.defaultDeny nor networkPolicy.defaultDeny is true"
        ),
        context={
            "global.network.defaultDeny": global_default_deny,
            "networkPolicy.defaultDeny": top_level_default_deny,
        },
    )
