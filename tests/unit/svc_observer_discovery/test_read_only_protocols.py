"""Structural proof that neither adapter Protocol has a write/mutate method.

Deliverable 5 / the shared negative test named in this unit's mission:
"any attempt to use a write/mutate method absent by construction" — this
is asserted here as a STRUCTURAL fact about `SiteCrawlerPort` and
`ObservationSourcePort` (both `typing.Protocol` classes), not a runtime
permission check: the method simply does not exist on the class at all, so
there is nothing for a caller to even attempt to call.
"""

from __future__ import annotations

import inspect

from saena_chatgpt_observer import ObservationSourcePort
from saena_site_discovery import SiteCrawlerPort

_MUTATION_VERBS = (
    "write",
    "put",
    "save",
    "delete",
    "update",
    "mutate",
    "set",
    "create",
    "remove",
    "post",
    "publish",
    "push",
)


def _public_protocol_methods(protocol: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(protocol)
        if not name.startswith("_") and callable(member)
    }


def test_site_crawler_port_has_exactly_two_read_methods_and_no_write_verb() -> None:
    methods = _public_protocol_methods(SiteCrawlerPort)
    assert methods == {"check_robots", "fetch_route"}
    for name in methods:
        assert not any(verb in name for verb in _MUTATION_VERBS), name


def test_observation_source_port_has_exactly_one_read_method_and_no_write_verb() -> None:
    methods = _public_protocol_methods(ObservationSourcePort)
    assert methods == {"capture_observation"}
    for name in methods:
        assert not any(verb in name for verb in _MUTATION_VERBS), name


def test_site_crawler_port_fake_has_no_extra_public_write_method() -> None:
    """Defense in depth: the reference fake adapter itself must not grow a
    write-shaped public method beyond what the Protocol declares (its
    call-recording lists/registration helpers are test-harness setup, not
    site-mutation capability, so they are explicitly excluded here)."""
    from saena_site_discovery import FakeSiteCrawler

    harness_setup_methods = {"register_route", "register_disallowed", "fail_next"}
    public_methods = _public_protocol_methods(FakeSiteCrawler) - harness_setup_methods
    assert public_methods == {"check_robots", "fetch_route"}


def test_observation_source_fake_has_no_extra_public_write_method() -> None:
    from saena_chatgpt_observer import FakeObservationSource

    harness_setup_methods = {"register_query", "fail_next"}
    public_methods = _public_protocol_methods(FakeObservationSource) - harness_setup_methods
    assert public_methods == {"capture_observation"}
