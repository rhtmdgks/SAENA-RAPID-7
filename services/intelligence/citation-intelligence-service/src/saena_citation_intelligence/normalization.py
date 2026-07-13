"""`normalize_url` — deterministic canonical citation URL form (w4-05).

Produces the `normalized_uri` value the `citation.normalized.v1` payload
contract requires: a string matching `uri_ref`
(`^[a-z0-9+.-]+://[^?#]+$`, `packages/contracts/json-schema/common/
identifiers/v1/identifiers.schema.json`) — **query strings and fragments are
structurally forbidden**, not merely "tracking params stripped" (ADR-0024
ruling R9-5, "presigned-token smuggling defense", cited verbatim in
`citation-normalized.schema.json`'s own `$comment` for this field). This
module therefore strips the ENTIRE query string and fragment on every input,
unconditionally — there is no "keep non-tracking query params" mode, because
the contract shape leaves no room for one.

Determinism contract (task brief): the SAME input URL string must always
normalize to a BYTE-IDENTICAL `normalized_uri` output, on every run/process/
machine, with no network access (IDN/punycode conversion uses only the
stdlib `idna` codec — no live DNS/WHOIS lookup).

Pipeline, in order:
    1. Reject empty/whitespace input.
    2. `urllib.parse.urlsplit` — structural parse (scheme/netloc/path/query/
       fragment). Reject a URL with no scheme or no host (a bare path like
       `/foo` or a relative reference is not a citable absolute URL).
    3. Scheme: lowercase (`urlsplit` already does this, kept explicit for
       clarity/documentation).
    4. Host: lowercase, then IDN/punycode-encode via `str.encode("idna")`
       (per-label; stdlib `idna` codec, RFC 3490) so a Unicode/IDN hostname
       and its already-punycode-encoded equivalent normalize to the SAME
       ASCII `xn--...` form. An already-ASCII host round-trips unchanged
       (case-folded).
    5. Port: dropped when it equals the scheme's well-known default
       (80/http, 443/https, 21/ftp) — `https://example.com:443/x` and
       `https://example.com/x` normalize identically; any other explicit
       port is kept verbatim (`:8080` etc.).
    6. Userinfo (`user:pass@`) is stripped entirely — never persisted in a
       citation record (credential-smuggling / PII defense, same spirit as
       `uri_ref`'s query/fragment ban).
    7. Path: percent-decode-then-re-encode is deliberately NOT performed
       (would risk changing semantics for paths containing legitimately
       percent-encoded reserved characters); this module instead performs
       purely structural path normalization: collapse `//` runs to `/`,
       resolve `.`/`..` segments (RFC 3986 §5.2.4 remove_dot_segments,
       applied via `posixpath.normpath`-equivalent hand-rolled logic — never
       imports `posixpath`, which is filesystem-flavored and mishandles a
       leading `//`), and apply the trailing-slash policy below. An empty
       path becomes `/` (a bare `https://example.com` cites the same
       resource as `https://example.com/`).
    8. Trailing-slash policy: a non-root path's trailing slash is dropped
       (`/a/b/` -> `/a/b`) UNLESS the path is exactly `/` (root always keeps
       its single slash — the alternative, an empty path, is not a valid
       `uri_ref` value since the pattern requires at least one character
       after `://`).
    9. Query string and fragment: always dropped (see contract note above).

Non-goals (explicit, out of this unit's scope per the task brief): this
module does NOT dereference the URL (no HTTP HEAD/GET to follow redirects,
detect a canonical `<link rel="canonical">`, or confirm the host resolves) —
it is pure string logic over the URL text as given.
"""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit

from saena_citation_intelligence.errors import UrlNormalizationError

_DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "ftp": 21,
}

# Schemes this module accepts for normalization. A citation is, by
# definition, a web-fetchable resource — non-fetchable schemes (mailto:,
# tel:, javascript:, data:, ...) are rejected rather than silently
# "normalized" into a shape that would misleadingly look like a fetchable
# citation URL.
_ACCEPTED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _encode_host(host: str) -> str:
    """Lowercase + IDN/punycode-encode `host` (stdlib `idna` codec).

    Raises `UrlNormalizationError` if `host` is empty or fails IDN encoding
    (e.g. malformed label lengths per RFC 3490) — never silently passes
    through a host this module could not deterministically canonicalize.
    """
    lowered = host.lower()
    try:
        encoded = lowered.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UrlNormalizationError(
            f"host {host!r} failed IDN/punycode encoding",
            context={"host": host},
        ) from exc
    if not encoded:
        raise UrlNormalizationError(
            f"host {host!r} encoded to an empty string", context={"host": host}
        )
    return encoded


def _split_netloc(netloc: str) -> tuple[str, int | None]:
    """Split a `urlsplit` netloc into `(host, port)`, discarding userinfo.

    `SplitResult.hostname`/`.port` already do this parsing (and lowercase
    the host) but raise a bare `ValueError` on a malformed port — re-raised
    here as `UrlNormalizationError` for this module's own error taxonomy.
    """
    parts = SplitResult(scheme="http", netloc=netloc, path="", query="", fragment="")
    try:
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UrlNormalizationError(
            f"netloc {netloc!r} has a malformed port", context={"netloc": netloc}
        ) from exc
    if not host:
        raise UrlNormalizationError(
            f"netloc {netloc!r} has no host component", context={"netloc": netloc}
        )
    return host, port


def _normalize_path(path: str) -> str:
    """Structural path normalization: collapse `//`, resolve `.`/`..`
    segments, apply trailing-slash policy. Never percent-decodes/re-encodes.

    Precondition (this module's only caller, `normalize_url`, always
    satisfies it — `urlsplit` on a `scheme://host...` URL never yields a
    non-empty relative path): `path` is either empty or starts with `/`.
    """
    if not path:
        return "/"

    trailing_slash = len(path) > 1 and path.endswith("/")

    segments = [seg for seg in path.split("/") if seg != ""]
    resolved: list[str] = []
    for seg in segments:
        if seg == ".":
            continue
        if seg == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(seg)

    if not resolved:
        return "/"

    normalized = "/" + "/".join(resolved)
    if trailing_slash:
        normalized += "/"

    # Trailing-slash policy: drop a non-root trailing slash.
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def normalize_url(raw_url: str) -> str:
    """Return the deterministic canonical form of `raw_url`.

    Raises `UrlNormalizationError` (fail closed) for empty input, a missing
    scheme/host, a scheme outside `{http, https}`, or an unencodable host.
    The output always matches the `uri_ref` contract pattern
    (`^[a-z0-9+.-]+://[^?#]+$`) — callers may rely on that without a second
    validation pass, though `records.py`'s `CitationRecord` re-validates it
    anyway (defense in depth, matching `ContentRecordProjection`'s own
    discipline for `evidence_ref`).
    """
    if not raw_url or not raw_url.strip():
        raise UrlNormalizationError("raw_url must be a non-empty string", context={})

    parts = urlsplit(raw_url.strip())

    scheme = parts.scheme.lower()
    if not scheme:
        raise UrlNormalizationError(
            f"raw_url {raw_url!r} has no scheme", context={"raw_url": raw_url}
        )
    if scheme not in _ACCEPTED_SCHEMES:
        raise UrlNormalizationError(
            f"scheme {scheme!r} is not a supported citation scheme ({sorted(_ACCEPTED_SCHEMES)!r})",
            context={"raw_url": raw_url, "scheme": scheme},
        )
    if not parts.netloc:
        raise UrlNormalizationError(
            f"raw_url {raw_url!r} has no host", context={"raw_url": raw_url}
        )

    host, port = _split_netloc(parts.netloc)
    encoded_host = _encode_host(host)

    default_port = _DEFAULT_PORTS.get(scheme)
    keep_port = port is not None and port != default_port
    authority = f"{encoded_host}:{port}" if keep_port else encoded_host

    normalized_path = _normalize_path(parts.path)

    return f"{scheme}://{authority}{normalized_path}"


__all__ = ["normalize_url"]
