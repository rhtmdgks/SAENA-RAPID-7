"""The six k3s spec §8.1 preflight checks, in the spec's own listed order.

`ALL_CHECKS` is the single source of truth for "what does `forgectl
preflight` run" — `saena_forgectl.preflight.run_preflight` iterates this
tuple, and `tests/unit/forgectl` asserts every entry here is exercised by
at least one passing and one failing fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from saena_forgectl.checks.engine_flags import check_engine_flags
from saena_forgectl.checks.external_secret_refs import check_external_secrets
from saena_forgectl.checks.image_digest_signature import check_image_digest_signature
from saena_forgectl.checks.migrations_reversible import check_migrations_reversible
from saena_forgectl.checks.network_policy import check_network_policy
from saena_forgectl.checks.service_account_permissions import (
    check_service_account_permissions,
)
from saena_forgectl.models import CheckResult

#: k3s spec §8.1's own fail-condition order: image digest/signature ->
#: engine flags -> external secrets -> network policy -> service account
#: permissions -> migrations.
ALL_CHECKS: tuple[Callable[[dict[str, Any]], CheckResult], ...] = (
    check_image_digest_signature,
    check_engine_flags,
    check_external_secrets,
    check_network_policy,
    check_service_account_permissions,
    check_migrations_reversible,
)

__all__ = [
    "ALL_CHECKS",
    "check_engine_flags",
    "check_external_secrets",
    "check_image_digest_signature",
    "check_migrations_reversible",
    "check_network_policy",
    "check_service_account_permissions",
]
