"""Image digest/signature check (k3s spec §8.1 condition 1: "required image
digest or signature is absent").

Values shape (k3s spec §7 skeleton + §6.3 "image는 ... signature 검증을
통과한다"):

```yaml
global:
  policyBundle:
    version: 1.0.0
    digest: sha256:REPLACE
  skillBundle:
    version: 1.0.0
    digest: sha256:REPLACE
images:
  - name: forge-console-api
    digest: sha256:...
    signature: sha256:...
  - name: agent-runner
    digest: sha256:...
    signature: sha256:...
```

Static-preflight scope note: this check verifies the values file
*declares* a digest and a signature reference for every listed image (and
for the policy/skill bundles) — it does not call out to a registry to
verify the signature cryptographically or confirm the digest actually
resolves (that is a live-cluster/registry-connected extension, out of
scope for W2A — see `tools/forgectl/README.md`).
"""

from __future__ import annotations

import re
from typing import Any

from saena_forgectl.models import CheckResult

CHECK_NAME = "image_digest_signature"

#: `sha256:` followed by 64 hex chars — the same shape every `digest:
#: sha256:REPLACE` placeholder in the k3s spec is meant to be filled in
#: with. `REPLACE` itself does not match and is therefore correctly
#: treated as "absent" — an un-filled-in placeholder is not a real digest.
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def _is_present_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST_PATTERN.match(value))


def _is_present_signature(value: Any) -> bool:
    # Signature references vary by signer (cosign bundle ref, sha256 of a
    # detached signature, etc.) — this static check only asserts a
    # non-empty string is declared, matching digest's non-placeholder
    # matching only loosely intentionally (cryptographic verification is
    # the documented live-cluster extension point, not this check's job).
    return isinstance(value, str) and value.strip() != "" and value.strip() != "REPLACE"


def check_image_digest_signature(values: dict[str, Any]) -> CheckResult:
    """Fail iff any declared image entry, or the policy/skill bundle, is
    missing a digest or a signature reference."""
    missing: list[dict[str, str]] = []

    images = values.get("images")
    if not isinstance(images, list) or len(images) == 0:
        missing.append({"item": "images", "problem": "no images declared"})
    else:
        for entry in images:
            if not isinstance(entry, dict):
                missing.append({"item": "images[]", "problem": "entry is not a mapping"})
                continue
            name = str(entry.get("name", "<unnamed>"))
            if not _is_present_digest(entry.get("digest")):
                missing.append({"item": name, "problem": "digest absent or not sha256:<64hex>"})
            if not _is_present_signature(entry.get("signature")):
                missing.append({"item": name, "problem": "signature absent"})

    global_section = values.get("global")
    if isinstance(global_section, dict):
        for bundle_key in ("policyBundle", "skillBundle"):
            bundle = global_section.get(bundle_key)
            if not isinstance(bundle, dict) or not _is_present_digest(bundle.get("digest")):
                missing.append({"item": bundle_key, "problem": "digest absent or not filled in"})
    else:
        missing.append({"item": "global", "problem": "global section not declared"})

    if missing:
        summary = "; ".join(f"{item['item']}: {item['problem']}" for item in missing)
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=f"missing required image digest/signature: {summary}",
            context={"missing": missing},
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=True,
        detail="every declared image and bundle has a digest and signature reference",
        context={"image_count": len(images) if isinstance(images, list) else 0},
    )
