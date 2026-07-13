"""Runner service-account permission check (k3s spec §8.1 condition 5:
"runner service account has cluster-admin or production deploy
permission").

Values shape (k3s spec §7 skeleton `agentRunner.job.serviceAccount` +
§5.3 "default service account는 API access를 갖지 않으며, 서비스별 minimal
RBAC만 부여한다"):

```yaml
agentRunner:
  enabled: true
  job:
    serviceAccount: saena-agent-runner
    rbac:
      clusterAdmin: false
      productionDeploy: false
      rules:
        - apiGroups: [""]
          resources: [pods]
          verbs: [get, list]
```

Static-preflight scope note: this check inspects the *declared* RBAC grant
flags/rules in the values file — it does not query a live cluster's
ClusterRoleBinding objects to confirm the actual bound permissions match
what was declared (live-cluster extension, out of scope for W2A).
"""

from __future__ import annotations

from typing import Any

from saena_forgectl.checks._util import get_path
from saena_forgectl.models import CheckResult

CHECK_NAME = "service_account_permissions"

#: Kubernetes RBAC verbs/resources that amount to a de facto cluster-admin
#: or production-deploy grant even if `rbac.clusterAdmin`/
#: `rbac.productionDeploy` were left `false` — a wildcard resource or verb,
#: or an explicit `cluster-admin` ClusterRole reference in a raw `rules`
#: list, is caught here too (fail closed on the substance, not just the
#: two named summary flags).
_DANGEROUS_VERBS = frozenset({"*"})
_DANGEROUS_RESOURCES = frozenset({"*"})
_DANGEROUS_CLUSTER_ROLE_NAMES = frozenset({"cluster-admin"})


def _rules_grant_dangerous_access(rules: Any) -> bool:
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        verbs = rule.get("verbs", [])
        resources = rule.get("resources", [])
        if isinstance(verbs, list) and any(v in _DANGEROUS_VERBS for v in verbs):
            return True
        if isinstance(resources, list) and any(r in _DANGEROUS_RESOURCES for r in resources):
            return True
    return False


def check_service_account_permissions(values: dict[str, Any]) -> CheckResult:
    """Fail iff the runner service account's declared RBAC grants
    cluster-admin or production-deploy permission — via the explicit
    summary flags, a wildcard rule, or a `cluster-admin` role reference."""
    rbac = get_path(values, "agentRunner", "job", "rbac")
    role_ref = get_path(values, "agentRunner", "job", "clusterRoleRef")

    if rbac is None and role_ref is None:
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail="agentRunner.job.rbac is not declared — runner RBAC must be explicit",
            context={},
        )

    problems: list[str] = []

    if isinstance(rbac, dict):
        if bool(rbac.get("clusterAdmin", False)):
            problems.append("rbac.clusterAdmin is true")
        if bool(rbac.get("productionDeploy", False)):
            problems.append("rbac.productionDeploy is true")
        if _rules_grant_dangerous_access(rbac.get("rules")):
            problems.append("rbac.rules grants a wildcard verb or resource")
    elif rbac is not None:
        problems.append(f"agentRunner.job.rbac must be a mapping, got {type(rbac).__name__}")

    if isinstance(role_ref, str) and role_ref in _DANGEROUS_CLUSTER_ROLE_NAMES:
        problems.append(f"clusterRoleRef is {role_ref!r}")

    if problems:
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail="runner service account has excessive permission: " + "; ".join(problems),
            context={"problems": problems},
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=True,
        detail="runner service account RBAC is minimal (no cluster-admin/production-deploy grant)",
        context={},
    )
