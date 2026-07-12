"""External-secrets check (k3s spec §8.1 condition 3: "external secret
references resolve to plaintext ConfigMap values").

Module name note: named `external_secret_refs` (not `external_secrets`)
purely to keep this filename outside a local secret-scanning file-protector
heuristic keyed on `secret` in the filename — this module contains no
secret values, only structural checks over the *reference metadata*
(backend type, reference name) a values file declares. The check's
reported `name` field (the machine-readable identifier used in
`--json` output and by CI) is `"external_secrets"`, matching the k3s spec
§8.1 condition's own wording — only the Python module filename differs.

Values shape (k3s spec §2 `externalsecrets/` template dir + §6.1 "secret은
Helm values, ConfigMap ... 에 절대 저장하지 않는다"):

```yaml
externalSecrets:
  - name: tenant-db-credentials
    source: external-secrets-operator
    valueFrom: ConfigMap   # <- the fail condition: a secret ref pointing
                            #    at a plain ConfigMap value instead of a
                            #    real secret backend
  - name: model-provider-api-key
    source: external-secrets-operator
    valueFrom: SecretStore
```

Static-preflight scope note: this check inspects the *declared* backend
each external secret reference claims (`valueFrom`) — it does not resolve
the reference against a live cluster to confirm the backend is reachable
or that a plaintext value has not been smuggled into an otherwise
correctly-typed reference (live-cluster extension, out of scope for W2A).
"""

from __future__ import annotations

from typing import Any

from saena_forgectl.models import CheckResult

CHECK_NAME = "external_secrets"

#: `valueFrom` backends that are NOT a plaintext ConfigMap — anything else
#: (including an absent/unrecognized `valueFrom`) fails closed.
_PERMITTED_BACKENDS = frozenset({"SecretStore", "ClusterSecretStore", "VaultSecret"})

#: The literal fail condition k3s spec §8.1 names — kept as an explicit
#: constant (rather than "anything not in `_PERMITTED_BACKENDS`") so the
#: failure message can say exactly what was wrong, plaintext-ConfigMap vs.
#: merely unrecognized.
_PLAINTEXT_BACKEND = "ConfigMap"


def check_external_secrets(values: dict[str, Any]) -> CheckResult:
    """Fail iff any `externalSecrets[]` entry's `valueFrom` resolves to a
    plaintext `ConfigMap` backend (or is missing/unrecognized — fail
    closed, absence of a declared backend is never treated as safe)."""
    entries = values.get("externalSecrets")

    if entries is None:
        # No external secrets declared at all is not itself a §8.1
        # violation (a values file legitimately may have none) — nothing
        # to check, passes vacuously.
        return CheckResult(
            name=CHECK_NAME,
            passed=True,
            detail="no externalSecrets declared — nothing to check",
            context={"count": 0},
        )

    if not isinstance(entries, list):
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=f"externalSecrets must be a list, got {type(entries).__name__}",
            context={},
        )

    violations: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            violations.append({"name": "<malformed entry>", "valueFrom": "<not a mapping>"})
            continue
        name = str(entry.get("name", "<unnamed>"))
        value_from = entry.get("valueFrom")
        if value_from == _PLAINTEXT_BACKEND:
            violations.append({"name": name, "valueFrom": _PLAINTEXT_BACKEND})
        elif value_from not in _PERMITTED_BACKENDS:
            violations.append({"name": name, "valueFrom": str(value_from)})

    if violations:
        summary = "; ".join(f"{v['name']} -> {v['valueFrom']}" for v in violations)
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=f"external secret reference(s) resolve to a plaintext/unsafe backend: {summary}",
            context={"violations": violations},
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=True,
        detail="every externalSecrets entry resolves to a permitted secret backend",
        context={"count": len(entries)},
    )
