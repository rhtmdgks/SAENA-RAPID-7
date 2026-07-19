"""Domain matrix — https-only, no local/private/metadata targets."""

from __future__ import annotations

import pytest
from saena_pilot.domain import validate_domain
from saena_pilot.errors import ValidationFailedError


@pytest.mark.parametrize(
    "domain",
    [
        "http://customer.example",
        "ftp://customer.example",
        "customer.example",  # no scheme
        "https://",  # no host
        "https:///path-only",
        "https://user:pass@customer.example",  # userinfo refused
        "https://localhost",
        "https://LOCALHOST",
        "https://app.localhost",
        "https://127.0.0.1",
        "https://127.9.9.9",  # whole 127/8
        "https://[::1]",
        "https://10.0.0.7",
        "https://172.16.0.1",
        "https://172.31.255.254",
        "https://192.168.1.1",
        "https://169.254.1.1",
        "https://169.254.169.254",  # cloud metadata endpoint
        "https://0.0.0.0",
        "https://service.internal",
        "https://printer.local",
    ],
)
def test_rejected_domains(domain: str) -> None:
    with pytest.raises(ValidationFailedError):
        validate_domain(domain)


@pytest.mark.parametrize(
    ("domain", "normalized"),
    [
        ("https://customer.example", "https://customer.example"),
        ("https://Customer.Example/", "https://customer.example"),
        ("https://customer.example:8443", "https://customer.example:8443"),
        ("https://sub.customer.example/path?q=1", "https://sub.customer.example"),
        ("https://xn--9n2bp8q.example", "https://xn--9n2bp8q.example"),
        # a genuinely public IP is allowed (only local/private ranges refuse)
        ("https://8.8.8.8", "https://8.8.8.8"),
    ],
)
def test_accepted_domains_normalize_to_origin(domain: str, normalized: str) -> None:
    assert validate_domain(domain) == normalized


def test_reject_reason_names_the_range() -> None:
    with pytest.raises(ValidationFailedError, match="loopback|private|link-local"):
        validate_domain("https://169.254.169.254")
