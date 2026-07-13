"""`saena_citation_intelligence.normalization.normalize_url` — determinism +
canonical-form cases (w4-05 task brief: "ports, tracking params, case, IDN,
fragments")."""

from __future__ import annotations

import re

import pytest
from saena_citation_intelligence.errors import UrlNormalizationError
from saena_citation_intelligence.normalization import normalize_url

_URI_REF_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")


def test_normalize_url_is_deterministic_same_input_same_output() -> None:
    raw = "HTTPS://Example.COM:443/a/b/?utm_source=x&utm_medium=y#frag"
    first = normalize_url(raw)
    second = normalize_url(raw)
    assert first == second


def test_normalize_url_output_always_matches_uri_ref_contract_pattern() -> None:
    for raw in (
        "https://example.com",
        "http://example.com:8080/a?b=1#c",
        "https://xn--caf-dma.com/menu",
        "https://café.com/menu",
    ):
        normalized = normalize_url(raw)
        assert _URI_REF_PATTERN.match(normalized), normalized


def test_scheme_and_host_are_lowercased() -> None:
    assert normalize_url("HTTPS://EXAMPLE.COM/Path") == "https://example.com/Path"


def test_default_https_port_is_removed() -> None:
    assert normalize_url("https://example.com:443/x") == normalize_url("https://example.com/x")
    assert normalize_url("https://example.com:443/x") == "https://example.com/x"


def test_default_http_port_is_removed() -> None:
    assert normalize_url("http://example.com:80/x") == "http://example.com/x"


def test_non_default_port_is_kept() -> None:
    assert normalize_url("https://example.com:8443/x") == "https://example.com:8443/x"


def test_tracking_query_params_are_stripped() -> None:
    assert (
        normalize_url("https://example.com/product?utm_source=newsletter&utm_campaign=q3")
        == "https://example.com/product"
    )


def test_non_tracking_query_params_are_also_stripped() -> None:
    """`normalized_uri` is `uri_ref`-shaped — query strings are structurally
    forbidden (ADR-0024 R9-5), not merely "tracking params" — so even a
    semantically-meaningful query param (`?id=42`) is dropped."""
    assert normalize_url("https://example.com/product?id=42") == "https://example.com/product"


def test_fragment_is_stripped() -> None:
    assert normalize_url("https://example.com/product#section-2") == "https://example.com/product"


def test_query_and_fragment_both_present_are_both_stripped() -> None:
    assert (
        normalize_url("https://example.com/product?utm_source=x#frag")
        == "https://example.com/product"
    )


def test_trailing_slash_dropped_for_non_root_path() -> None:
    assert normalize_url("https://example.com/a/b/") == "https://example.com/a/b"


def test_root_path_keeps_single_slash() -> None:
    assert normalize_url("https://example.com/") == "https://example.com/"
    assert normalize_url("https://example.com") == "https://example.com/"


def test_double_slash_runs_are_collapsed() -> None:
    assert normalize_url("https://example.com/a//b///c") == "https://example.com/a/b/c"


def test_dot_segments_are_resolved() -> None:
    assert normalize_url("https://example.com/a/./b/../c") == "https://example.com/a/c"


def test_dot_dot_above_root_is_absorbed_not_negative() -> None:
    assert normalize_url("https://example.com/../a") == "https://example.com/a"


def test_idn_hostname_encodes_to_punycode() -> None:
    assert normalize_url("https://café.com/menu") == "https://xn--caf-dma.com/menu"


def test_already_punycode_hostname_round_trips_unchanged() -> None:
    assert normalize_url("https://xn--caf-dma.com/menu") == "https://xn--caf-dma.com/menu"


def test_idn_and_punycode_equivalent_inputs_normalize_identically() -> None:
    assert normalize_url("https://café.com/menu") == normalize_url("https://xn--caf-dma.com/menu")


def test_userinfo_is_stripped() -> None:
    assert normalize_url("https://user:pass@example.com/x") == "https://example.com/x"


def test_mixed_case_host_various_forms_normalize_identically() -> None:
    variants = [
        "https://EXAMPLE.com/x",
        "https://Example.Com/x",
        "https://example.COM/x",
    ]
    normalized = {normalize_url(v) for v in variants}
    assert normalized == {"https://example.com/x"}


def test_empty_string_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("   ")


def test_missing_scheme_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("example.com/path")


def test_missing_host_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("https:///path")


def test_disallowed_scheme_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("mailto:someone@example.com")


def test_javascript_scheme_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("javascript:alert(1)")


def test_ftp_scheme_raises_not_in_accepted_set() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("ftp://example.com/file")


def test_malformed_port_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("https://example.com:notaport/x")


def test_error_context_carries_raw_url() -> None:
    try:
        normalize_url("mailto:someone@example.com")
    except UrlNormalizationError as exc:
        assert exc.context.get("raw_url") == "mailto:someone@example.com"
    else:
        pytest.fail("expected UrlNormalizationError")


def test_leading_and_trailing_whitespace_around_url_is_stripped_before_parsing() -> None:
    assert normalize_url("  https://example.com/x  ") == "https://example.com/x"
