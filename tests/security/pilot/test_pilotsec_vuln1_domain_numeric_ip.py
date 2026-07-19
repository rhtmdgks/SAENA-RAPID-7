"""VULN-1 reproduction: non-canonical numeric IP encodings bypass the
loopback/private/unspecified rejection in `saena_pilot.domain.validate_domain`.

The domain is bound into evidence and consumed by later units (w6-12 discovery
adapters that MAY fetch). `validate_domain` documents that it rejects loopback,
RFC1918, link-local and the cloud-metadata endpoint — but `ipaddress.ip_address`
only parses canonical dotted/colon forms, so integer / hex / octal / short-form
spellings fell through the `ip is None` branch and were ACCEPTED. A downstream
HTTP client resolves e.g. `2130706433` -> 127.0.0.1: classic SSRF.

FIXED at w6-13 integration: `saena_pilot.domain._canonical_ipv4` canonicalizes
inet_aton-style numeric encodings before the loopback/private test, so these
forms are now rejected. This test asserts the hardened behavior (was a strict
xfall reproduction; flipped to a positive regression guard once patched).
"""

from __future__ import annotations

import pytest
from saena_pilot.domain import validate_domain
from saena_pilot.errors import ValidationFailedError


@pytest.mark.parametrize(
    "domain",
    [
        "https://2130706433",  # decimal 127.0.0.1
        "https://0x7f000001",  # hex 127.0.0.1
        "https://0x7f.1",  # mixed hex/short 127.0.0.1
        "https://127.1",  # short-form 127.0.0.1
        "https://0",  # 0.0.0.0 unspecified
        "https://0300.0250.0.1",  # octal 192.168.0.1
    ],
)
def test_numeric_encoded_private_host_should_be_rejected(domain: str) -> None:
    with pytest.raises(ValidationFailedError):
        validate_domain(domain)


def test_canonical_forms_are_rejected_regression_anchor() -> None:
    # Proves the guard DOES reject the canonical spellings — VULN-1 is strictly
    # the non-canonical-encoding gap above, not a total failure of the filter.
    for domain in ("https://127.0.0.1", "https://192.168.0.1", "https://0.0.0.0"):
        with pytest.raises(ValidationFailedError):
            validate_domain(domain)
