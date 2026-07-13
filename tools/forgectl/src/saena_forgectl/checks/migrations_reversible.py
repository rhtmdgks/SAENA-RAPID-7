"""Migration reversibility check (k3s spec §8.1 condition 6: "migrations
are non-reversible or unreviewed").

Values shape (k3s spec §2 `migrations/` template dir + §8.2 "migration
service는 expand/contract migration을 사용한다. destructive schema
migration은 별도 승인 runbook으로 분리한다"):

```yaml
migrations:
  - id: 2026_07_add_tenant_column
    strategy: expand-contract
    reversible: true
    reviewedBy: alice
  - id: 2026_07_drop_legacy_table
    strategy: destructive
    reversible: false
    reviewedBy: null
```

Static-preflight scope note: this check inspects the declared
`reversible`/`reviewedBy` metadata for each listed migration — it does not
execute or dry-run the migration to independently confirm reversibility
(live-cluster/database-connected extension, out of scope for W2A).
"""

from __future__ import annotations

from typing import Any

from saena_forgectl.models import CheckResult

CHECK_NAME = "migrations_reversible"


def _is_reviewed(reviewed_by: Any) -> bool:
    return isinstance(reviewed_by, str) and reviewed_by.strip() != ""


def check_migrations_reversible(values: dict[str, Any]) -> CheckResult:
    """Fail iff any declared migration is non-reversible or unreviewed.

    No `migrations` key declared at all passes vacuously (a values file
    for a release with no pending migrations is legitimate).
    """
    migrations = values.get("migrations")

    if migrations is None:
        return CheckResult(
            name=CHECK_NAME,
            passed=True,
            detail="no migrations declared — nothing to check",
            context={"count": 0},
        )

    if not isinstance(migrations, list):
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=f"migrations must be a list, got {type(migrations).__name__}",
            context={},
        )

    violations: list[dict[str, Any]] = []
    for entry in migrations:
        if not isinstance(entry, dict):
            violations.append({"id": "<malformed entry>", "problem": "entry is not a mapping"})
            continue
        migration_id = str(entry.get("id", "<unnamed>"))
        reversible = bool(entry.get("reversible", False))
        reviewed = _is_reviewed(entry.get("reviewedBy"))

        problems: list[str] = []
        if not reversible:
            problems.append("non-reversible")
        if not reviewed:
            problems.append("unreviewed")
        if problems:
            violations.append({"id": migration_id, "problem": ", ".join(problems)})

    if violations:
        summary = "; ".join(f"{v['id']} ({v['problem']})" for v in violations)
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=f"migration(s) are non-reversible or unreviewed: {summary}",
            context={"violations": violations},
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=True,
        detail="every declared migration is reversible and reviewed",
        context={"count": len(migrations)},
    )
