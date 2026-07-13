"""Shared test-fixture factories for `tests/unit/svc_demand_graph`."""

from __future__ import annotations

from typing import Any

from saena_demand_graph.records import FirstPartyMaterial, MaterialSourceKind

DEFAULT_TENANT_ID = "acme-inc"
DEFAULT_PROJECT_ID = "proj-1"


def make_material(
    *,
    material_id: str = "m1",
    source_kind: MaterialSourceKind = MaterialSourceKind.SALES_TRANSCRIPT,
    text: str = "what is your pricing plan",
    locale: str = "en-US",
    provenance_ref: str = "doc://sales/call-1",
) -> FirstPartyMaterial:
    return FirstPartyMaterial(
        material_id=material_id,
        source_kind=source_kind,
        text=text,
        locale=locale,
        provenance_ref=provenance_ref,
    )


#: One material per intent label — deliberately hits every branch of
#: `builder._INTENT_KEYWORDS` so `test_intent_labelling.py` can assert every
#: label is reachable, not just a couple of happy-path cases.
INTENT_SAMPLE_TEXT: dict[str, str] = {
    "definition": "what is a demand graph, please explain",
    "integration": "how do I integrate the api with a webhook connector",
    "security": "what is your soc 2 compliance and encryption policy",
    "pricing": "what is the pricing plan and billing cost",
    "comparison": "how does this compare, product a vs product b alternative",
    "implementation": "getting started: how do i configure and install this",
    "migration": "how do i migrate and import data, switch from a legacy tool",
    "support": "I have an error, the button is not working, please help troubleshoot",
    "procurement": "we need a vendor contract and purchase order for procurement",
}


def make_materials_for_all_intents(
    *, locale: str = "en-US", tenant_prefix: str = "m"
) -> list[FirstPartyMaterial]:
    return [
        make_material(
            material_id=f"{tenant_prefix}-{intent}",
            text=text,
            locale=locale,
            provenance_ref=f"doc://source/{intent}",
        )
        for intent, text in INTENT_SAMPLE_TEXT.items()
    ]


def make_envelope_kwargs_recorder() -> tuple[list[dict[str, Any]], Any]:
    """Return `(calls, fake_port)` — `fake_port` is a deterministic
    `events.EventEnvelopeBuilderPort`-shaped callable that records every
    call's kwargs into `calls` and returns a small deterministic dict
    (mirrors `saena_site_discovery.crawler.FakeSiteCrawler`'s "records every
    call it receives" discipline, applied to this port instead)."""
    calls: list[dict[str, Any]] = []

    def _fake_port(
        *,
        producer: str,
        event_type: str,
        tenant_id: str,
        run_id: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorded = {
            "producer": producer,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "payload": payload,
        }
        calls.append(recorded)
        return {"context_type": "tenant", **recorded}

    return calls, _fake_port
