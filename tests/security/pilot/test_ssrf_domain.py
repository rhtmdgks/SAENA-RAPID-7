"""Attack 5 — SSRF / localhost / private / metadata domains.

`validate_domain` is the SSRF-adjacent gate: https-only, no userinfo, and a
rejection of loopback / private / link-local / metadata / `.internal` /
`.local` hosts. Each rejected shape asserts `ValidationFailedError` (and, for
a sample, `EXIT_VALIDATION_FAILED` = 1 through the CLI); a normal public https
domain is accepted and normalized to its origin.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED, main
from saena_pilot.domain import validate_domain
from saena_pilot.errors import ValidationFailedError

REJECTED = [
    "http://customer.example",  # non-https scheme
    "ftp://customer.example",
    "//customer.example",  # scheme-less
    "https://localhost",
    "https://localhost:8080",
    "https://127.0.0.1",
    "https://127.5.5.5",
    "https://[::1]",  # ipv6 loopback
    "https://10.0.0.5",
    "https://10.255.1.1",
    "https://172.16.0.1",
    "https://172.31.255.1",
    "https://192.168.1.1",
    "https://169.254.169.254",  # cloud metadata endpoint
    "https://169.254.0.1",
    "https://[::]",  # unspecified
    "https://0.0.0.0",
    "https://app.internal",
    "https://db.local",
    "https://host.localhost",
    "https://user:pass@customer.example",  # userinfo/credentials
    "https://",  # missing host
]


class TestRejectedDomains:
    @pytest.mark.parametrize("domain", REJECTED)
    def test_domain_rejected(self, domain: str) -> None:
        with pytest.raises(ValidationFailedError):
            validate_domain(domain)


class TestMetadataAndPrivateCliExit:
    @pytest.mark.parametrize(
        "domain",
        [
            "http://customer.example",
            "https://169.254.169.254",
            "https://localhost",
            "https://10.0.0.1",
        ],
    )
    def test_bad_domain_cli_exit_validation_failed(
        self,
        domain: str,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            domain,
            "--mode",
            "audit",
            "--dry-run",
        ]
        assert main(argv) == EXIT_VALIDATION_FAILED
        capsys.readouterr()


class TestAcceptedDomains:
    @pytest.mark.parametrize(
        "domain,expected",
        [
            ("https://customer.example", "https://customer.example"),
            ("https://Customer.Example", "https://customer.example"),
            ("https://customer.example:8443", "https://customer.example:8443"),
            ("https://app.customer.co.uk", "https://app.customer.co.uk"),
            ("https://customer.example.", "https://customer.example"),  # trailing dot normalized
        ],
    )
    def test_public_https_domain_accepted(self, domain: str, expected: str) -> None:
        assert validate_domain(domain) == expected

    def test_accepted_domain_cli_exit_ok(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            "https://customer.example",
            "--mode",
            "audit",
            "--dry-run",
        ]
        assert main(argv) == EXIT_OK
        capsys.readouterr()
