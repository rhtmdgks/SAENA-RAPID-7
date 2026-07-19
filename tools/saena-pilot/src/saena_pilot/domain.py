"""Deployed-domain validation.

The domain is used for discovery/verification identity ONLY — this unit never
fetches it. Validation is fail-closed against SSRF-adjacent shapes anyway,
because the value is bound into evidence and later units will consume it:

- https scheme only (no http, no other scheme)
- hostname required; no userinfo (credentials in URLs are refused)
- literal loopback (localhost / 127.0.0.0/8 / ::1), private ranges (10/8,
  172.16/12, 192.168/16), link-local 169.254/16 (incl. the metadata endpoint
  169.254.169.254), unspecified/reserved/multicast addresses, and the
  `.internal` / `.local` suffixes are all rejected.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from saena_pilot.errors import ValidationFailedError

_REJECTED_HOST_SUFFIXES = (".internal", ".local", ".localhost")
_REJECTED_HOSTS = ("localhost", "internal", "local")


def _reject(domain: str, reason: str) -> ValidationFailedError:
    return ValidationFailedError(
        f"--domain {domain!r} rejected: {reason}",
        context={"domain": domain, "reason": reason},
    )


def _canonical_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Resolve classic inet_aton-style numeric IPv4 encodings to an address.

    `ipaddress.ip_address` only accepts canonical dotted-quad, so non-canonical
    encodings of internal hosts — `2130706433`, `0x7f000001`, `0177.0.0.1`,
    `127.1`, `0` — slip past the loopback/private test as if they were opaque
    hostnames (SSRF-adjacent, VULN-1 w6-13). This mirrors inet_aton's octal/hex
    and short-form rules deterministically so those forms canonicalize to the
    same address the private/loopback checks then reject. Returns None when the
    host is not a numeric IPv4 encoding (i.e. a real DNS name).
    """
    parts = host.split(".")
    if len(parts) > 4:
        return None
    values: list[int] = []
    for part in parts:
        if part == "" or (part[0] == "-"):
            return None
        try:
            lowered_part = part.lower()
            if lowered_part.startswith("0x"):
                values.append(int(part, 16))
            elif part[0] == "0" and part != "0":
                # Classic leading-zero octal (inet_aton). Python's int(x, 0)
                # REJECTS "0300" (needs "0o300"), so parse octal explicitly.
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
        except ValueError:
            return None
    # A single all-decimal label like "example" already failed int(); a genuine
    # DNS label with digits + letters (e.g. "abc123") also fails, so anything
    # reaching here is purely numeric. Reconstruct per inet_aton part-count rules.
    n = len(values)
    if any(v < 0 for v in values):
        return None
    if n == 1:
        packed = values[0]
    elif n == 2:  # a.(24-bit b)
        a, b = values
        if a > 0xFF or b > 0xFFFFFF:
            return None
        packed = (a << 24) | b
    elif n == 3:  # a.b.(16-bit c)
        a, b, c = values
        if a > 0xFF or b > 0xFF or c > 0xFFFF:
            return None
        packed = (a << 24) | (b << 16) | c
    else:  # n == 4, classic dotted quad
        if any(v > 0xFF for v in values):
            return None
        packed = (values[0] << 24) | (values[1] << 16) | (values[2] << 8) | values[3]
    if packed > 0xFFFFFFFF:
        return None
    return ipaddress.IPv4Address(packed)


def validate_domain(domain: str) -> str:
    """Validate and return the normalized origin (`https://<host>[:port]`).

    Raises `ValidationFailedError` on any rejected shape.
    """
    try:
        parts = urlsplit(domain)
    except ValueError as exc:
        raise _reject(domain, f"unparsable URL ({exc})") from exc

    if parts.scheme != "https":
        raise _reject(domain, f"scheme must be https, got {parts.scheme or '(none)'!r}")
    if parts.username is not None or parts.password is not None:
        raise _reject(domain, "userinfo (credentials) in the URL is not allowed")

    try:
        hostname = parts.hostname
    except ValueError as exc:
        raise _reject(domain, f"invalid host ({exc})") from exc
    if not hostname:
        raise _reject(domain, "hostname is required")

    lowered = hostname.lower().rstrip(".")
    if lowered in _REJECTED_HOSTS:
        raise _reject(domain, f"host {lowered!r} is not a deployed public domain")
    if any(lowered.endswith(suffix) for suffix in _REJECTED_HOST_SUFFIXES):
        raise _reject(domain, f"host suffix of {lowered!r} is not a deployed public domain")

    ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        # Not canonical — try classic numeric IPv4 encodings (VULN-1 hardening).
        ip = _canonical_ipv4(lowered)
    if ip is not None and (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise _reject(domain, f"IP literal {lowered!r} is loopback/private/link-local/reserved")

    port = f":{parts.port}" if parts.port is not None else ""
    return f"https://{lowered}{port}"
