"""POST /v1/audit/entries — append happy path + chain growth."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import TENANT_A, make_append_body, roles_header
from saena_audit_ledger import create_app
from saena_domain.audit import AuditEntry
from saena_domain.audit.chain import build_entry
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryAuditLedger


def test_append_returns_201_with_computed_hash(client: TestClient) -> None:
    resp = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("service")
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["event_hash"].startswith("sha256:")
    assert body["prev_event_hash"] is None
    assert body["action"] == "patch.unit.completed.v1"
    assert body["tenant_id"] == TENANT_A


def test_append_does_not_accept_caller_supplied_hash(client: TestClient) -> None:
    """`event_hash`/`prev_event_hash` are not fields of the request model —
    a caller attempting to supply either is rejected by pydantic's
    `extra="forbid"` (422), never silently ignored or trusted.

    Hardened (critic SHOULD-FIX, w2-10 review): also asserts problem+json
    content-type and that the injected (fake but still caller-supplied)
    hash value never appears anywhere in the raw response text — the
    `RequestValidationError` handler must not echo the rejected `extra`
    field's value back."""
    injected_hash = "sha256:" + "0" * 64
    payload = make_append_body()
    payload["event_hash"] = injected_hash

    resp = client.post("/v1/audit/entries", json=payload, headers=roles_header("service"))

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert injected_hash not in resp.text
    body = resp.json()
    assert body["error_code"] == "saena.audit_ledger.validation_failed"


def test_second_append_links_to_first_via_computed_prev_hash(client: TestClient) -> None:
    first = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("service")
    ).json()

    second = client.post(
        "/v1/audit/entries",
        json=make_append_body(payload={"patch_unit_id": "second"}),
        headers=roles_header("service"),
    ).json()

    assert second["prev_event_hash"] == first["event_hash"]
    assert second["event_hash"] != first["event_hash"]


def test_chain_grows_and_is_readable_in_order(client: TestClient) -> None:
    for i in range(3):
        client.post(
            "/v1/audit/entries",
            json=make_append_body(payload={"patch_unit_id": f"unit-{i}"}),
            headers=roles_header("service"),
        )

    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), **{"X-Saena-Tenant-Id": TENANT_A}},
    )

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 3
    assert [e["payload"]["patch_unit_id"] for e in entries] == [
        "unit-0",
        "unit-1",
        "unit-2",
    ]
    # prev_event_hash chains through in order.
    assert entries[1]["prev_event_hash"] == entries[0]["event_hash"]
    assert entries[2]["prev_event_hash"] == entries[1]["event_hash"]


def test_system_scope_append_omits_tenant_id(client: TestClient) -> None:
    body = make_append_body(scope="system", tenant_id=None, run_id=None)

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert resp.status_code == 201
    assert resp.json()["scope"] == "system"
    assert resp.json()["tenant_id"] is None


def test_malformed_action_pattern_is_validation_error_not_forbidden_data(
    client: TestClient,
) -> None:
    """`build_entry` raises a `pydantic.ValidationError` (via `AuditEntry`
    re-validation) for a structurally invalid field, not
    `ForbiddenAuditDataError` — routed through `validation_error_problem`
    (critic MUST-FIX 1), never `str(exc)`, so the rejected value never
    appears in the response."""
    injected_action = "not-a-valid-action"
    body = make_append_body(action=injected_action)

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert injected_action not in resp.text
    problem = resp.json()
    assert problem["error_code"] == "saena.audit_ledger.validation_failed"
    assert problem["errors"] == [
        {
            "type": "string_pattern_mismatch",
            "loc": ["action"],
            "msg": (
                "String should match pattern '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){2,3}\\.v[0-9]+$'"
            ),
        }
    ]


def test_tenant_scope_with_malformed_tenant_id_is_identity_error_400(client: TestClient) -> None:
    """`scope="tenant"` with a `tenant_id` that fails the ADR-0014 pattern
    raises `InvalidTenantIdError` from `_resolve_scope_tenant`, caught by
    the module-level `IdentityError` exception handler (not an inline
    try/except in the handler body)."""
    body = make_append_body(tenant_id="NOT_VALID_!!")

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "saena.identity.invalid_tenant_id"


class _RacyLedger:
    """Wraps a real `InMemoryAuditLedger`, returning a STALE (empty)
    `read_range` result on its FIRST call only — simulates a concurrent
    append landing between this handler's own tail lookup and its own
    `append` call: the handler computes `prev_hash=None` from the stale
    read, but the real chain already has a tail by the time `ledger.append`
    runs, so the append is rejected for a broken link — deterministically
    exercising the handler's `ledger.append` `ValueError` branch (distinct
    from the earlier `build_entry` `ValueError` branch) without relying on
    real thread interleaving timing.
    """

    def __init__(self, real: InMemoryAuditLedger) -> None:
        self._real = real
        self._stale_read_served = False

    def append(self, entry: AuditEntry) -> AuditEntry:
        return self._real.append(entry)

    def read_range(
        self,
        *,
        tenant_id: TenantId | None = None,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> tuple[AuditEntry, ...]:
        if not self._stale_read_served:
            self._stale_read_served = True
            return ()  # stale: reports an empty chain even though one exists below
        return self._real.read_range(
            tenant_id=tenant_id, start_index=start_index, end_index=end_index
        )

    def verify(self, *, tenant_id: TenantId | None = None) -> tuple[bool, int | None]:
        return self._real.verify(tenant_id=tenant_id)


def test_append_rejects_when_chain_tail_advanced_between_read_and_append(
    ledger: InMemoryAuditLedger,
) -> None:
    # Land a genuine first entry directly on the real ledger BEFORE the racy
    # wrapper is even attached — the real chain already has a tail.
    pre_existing = build_entry(
        prev_hash=None,
        action="patch.unit.completed.v1",
        recorded_at="2026-07-12T09:14:32Z",
        scope="tenant",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        payload={"patch_unit_id": "pre-existing"},
        tenant_id=TENANT_A,
        run_id="run-2026-0712-0007",
    )
    ledger.append(pre_existing)

    racy = _RacyLedger(ledger)
    racy_client = TestClient(create_app(racy))  # type: ignore[arg-type]

    resp = racy_client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("service")
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "saena.audit_ledger.chain_link_rejected"
