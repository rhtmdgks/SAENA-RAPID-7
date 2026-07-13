"""Artifact single-gateway (w4-08): raw content flows OUT only through the
gateway, which returns an opaque ref + hash — never raw bytes back into the
observation path; cross-tenant reads are fail-closed."""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway, RawArtifactRef
from saena_chatgpt_observer.errors import CrossTenantObservationError

from .conftest import TENANT_A, TENANT_B

RAW = b"<html>rendered chatgpt-search result</html>"


def test_put_returns_ref_and_hash_never_raw_bytes() -> None:
    gw = FakeArtifactGateway()
    ref = gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    assert isinstance(ref, RawArtifactRef)
    assert ref.artifact_hash.startswith("sha256:")
    assert ref.raw_object_ref.startswith("artifact://")
    # the ref object carries NO raw bytes anywhere on it
    assert RAW not in ref.raw_object_ref.encode()
    assert not any(isinstance(v, bytes) for v in (ref.raw_object_ref, ref.artifact_hash))


def test_hash_is_deterministic_content_address() -> None:
    gw = FakeArtifactGateway()
    r1 = gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    r2 = gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    assert r1.artifact_hash == r2.artifact_hash  # same content → same hash


def test_round_trip_read_back_within_tenant() -> None:
    gw = FakeArtifactGateway()
    ref = gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    assert gw.get_raw_artifact(tenant_id=TENANT_A, ref=ref) == RAW


def test_cross_tenant_read_is_fail_closed() -> None:
    gw = FakeArtifactGateway()
    ref = gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    with pytest.raises(CrossTenantObservationError):
        gw.get_raw_artifact(tenant_id=TENANT_B, ref=ref)


def test_unknown_hash_under_own_tenant_is_fail_closed() -> None:
    gw = FakeArtifactGateway()
    gw.put_raw_artifact(tenant_id=TENANT_A, raw_content=RAW)
    forged = RawArtifactRef(
        raw_object_ref=f"artifact://{TENANT_A}/{'0' * 64}", artifact_hash="sha256:" + "0" * 64
    )
    with pytest.raises(CrossTenantObservationError):
        gw.get_raw_artifact(tenant_id=TENANT_A, ref=forged)
