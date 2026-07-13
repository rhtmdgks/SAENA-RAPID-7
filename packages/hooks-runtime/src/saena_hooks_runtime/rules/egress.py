"""`deny_unapproved_network_egress` matcher.

Default-deny: a network-capable binary invocation is denied unless its
target host is loopback or appears in the caller-supplied
`approved_domains` allowlist (task instructions do not add an egress
allowlist field to the `ActionContract` model; `pre_tool_use` threads one
through as a separate parameter — see that module's docstring for why).
"""

from __future__ import annotations

from urllib.parse import urlparse

_NETWORK_BINARIES = frozenset(
    {"curl", "wget", "nc", "ncat", "ssh", "scp", "rsync", "ftp", "http", "https"}
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _extract_host(tokens: list[str]) -> str | None:
    for tok in tokens[1:]:
        if "://" in tok:
            parsed = urlparse(tok)
            if parsed.hostname:
                return parsed.hostname
        if "@" in tok and ":" in tok.split("@", 1)[1]:
            # scp/rsync-style user@host:path
            return tok.split("@", 1)[1].split(":", 1)[0]
        if "@" in tok and not tok.startswith("-"):
            return tok.split("@", 1)[1]
    # bare `ssh host` / `nc host port` form — first non-flag token
    for tok in tokens[1:]:
        if not tok.startswith("-"):
            return tok
    return None


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def matches_unapproved_egress(segment: str, approved_domains: tuple[str, ...]) -> str | None:
    """Return a short match description, or `None` if `segment` is not a
    network call, or targets an approved/loopback host."""
    tokens = segment.split()
    if not tokens:
        return None
    head = tokens[0]
    if head not in _NETWORK_BINARIES:
        return None
    host = _extract_host(tokens)
    if host is None:
        return f"{head} network call with unresolvable target"
    if _is_loopback(host):
        return None
    if host in approved_domains:
        return None
    return f"{head} egress to unapproved host '{host}'"


__all__ = ["matches_unapproved_egress"]
