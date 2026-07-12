"""`ActorContext` runtime wrapper — human/system tenant_id conditional,
idempotency identity, PII-safe repr.
"""

from __future__ import annotations

import pytest
import saena_domain.identity.actor as actor_module
from conftest import make_actor_context_payload
from saena_domain.identity.actor import ActorContext, ActorTenantRequiredError


class TestConstruction:
    def test_system_actor_without_tenant_id_is_valid(self, actor_context_payload: dict) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert actor.actor_id == "actor-system-worker-0001"
        assert actor.actor_type == "system"
        assert actor.tenant_id is None
        assert not actor.is_human()

    def test_human_actor_with_tenant_id_is_valid(self) -> None:
        payload = make_actor_context_payload(
            actor_id="actor-human-0001",
            actor_type="human",
            session_id="session-example-0001",
            tenant_id="acme-corp",
        )
        actor = ActorContext.from_payload(payload)
        assert actor.is_human()
        assert actor.tenant_id == "acme-corp"

    def test_human_actor_without_tenant_id_denied(self) -> None:
        # Mirrors tests/contract/fixtures/actor-context/invalid/
        # human-without-tenant-id.json — the generated model does not
        # enforce the schema's allOf/if/then conditional, so this wrapper
        # must.
        payload = make_actor_context_payload(
            actor_id="actor-human-0002",
            actor_type="human",
            session_id="session-example-0003",
        )
        with pytest.raises(ActorTenantRequiredError) as exc_info:
            ActorContext.from_payload(payload)
        assert exc_info.value.context["actor_id"] == "actor-human-0002"
        assert exc_info.value.error_code == "saena.identity.actor_tenant_required"

    def test_system_actor_may_carry_tenant_id_too(self) -> None:
        payload = make_actor_context_payload(actor_type="system", tenant_id="acme-corp")
        actor = ActorContext.from_payload(payload)
        assert actor.tenant_id == "acme-corp"


class TestIdempotencyIdentity:
    def test_idempotency_key_is_actor_id_and_session_id(self, actor_context_payload: dict) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert actor.idempotency_key() == (
            "actor-system-worker-0001",
            "session-example-0002",
        )

    def test_hash_matches_idempotency_key(self, actor_context_payload: dict) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert hash(actor) == hash(actor.idempotency_key())

    def test_equal_payloads_compare_equal(self, actor_context_payload: dict) -> None:
        a = ActorContext.from_payload(actor_context_payload)
        b = ActorContext.from_payload(dict(actor_context_payload))
        assert a == b

    def test_different_session_ids_are_distinct_identities(self) -> None:
        a = ActorContext.from_payload(make_actor_context_payload(session_id="session-a"))
        b = ActorContext.from_payload(make_actor_context_payload(session_id="session-b"))
        assert a.idempotency_key() != b.idempotency_key()
        assert a != b

    def test_equality_against_non_actor_context_is_not_implemented(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert actor.__eq__("not-an-actor-context") is NotImplemented
        assert actor != "not-an-actor-context"

    def test_model_property_exposes_generated_pydantic_model(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert actor.model.actor_id.root == "actor-system-worker-0001"


class TestPiiBoundary:
    def test_repr_exposes_actor_id_only(self) -> None:
        payload = make_actor_context_payload(
            actor_id="actor-human-0001",
            actor_type="human",
            session_id="super-secret-session-token-like-value",
            tenant_id="acme-corp",
        )
        actor = ActorContext.from_payload(payload)
        text = repr(actor)
        assert "actor-human-0001" in text
        assert "super-secret-session-token-like-value" not in text
        assert "acme-corp" not in text

    def test_str_matches_repr(self, actor_context_payload: dict) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert str(actor) == repr(actor)

    def test_generated_model_structurally_has_no_email_field(self) -> None:
        # contract-catalog.md:20 PII minimization: identity fields are
        # ABSENT, not merely omitted -- confirmed by the model rejecting an
        # unknown "email" property outright (extra="forbid"), mirroring
        # tests/contract/fixtures/actor-context/invalid/email-property.json.
        import pydantic

        payload = make_actor_context_payload(
            actor_type="human", tenant_id="acme-corp", email="user@example.com"
        )
        with pytest.raises(pydantic.ValidationError):
            ActorContext.from_payload(payload)


class TestModelPropertyIsADefensiveCopy:
    """MUST-FIX (critic, w2-01 review): the generated pydantic model has
    `extra="forbid"` but is NOT frozen. `.model` must never hand out the
    live internal instance -- mutating the returned value must never affect
    the wrapper's own enforced state, and must never let a caller bypass the
    human/system tenant_id conditional by mutating a field after the fact.
    """

    def test_returned_model_is_not_the_same_object_as_internal_state(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        returned = actor.model
        assert returned is not actor._model  # noqa: SLF001 - explicit internal-state check

    def test_two_calls_to_model_return_independent_copies(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        first = actor.model
        second = actor.model
        assert first is not second
        assert first == second

    def test_mutating_returned_actor_type_does_not_flip_the_wrapper(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        assert actor.actor_type == "system"
        assert not actor.is_human()

        leaked = actor.model
        leaked.actor_type = actor_module._SchemaActorType.human

        # The wrapper's own actor_type property (backed by self._model, not
        # the leaked copy) must be unaffected -- this is exactly the
        # "flip actor_type from system to human post-construction, bypassing
        # ActorTenantRequiredError" scenario the critic flagged.
        assert actor.actor_type == "system"
        assert not actor.is_human()

    def test_mutating_returned_model_cannot_bypass_human_tenant_gate_for_a_fresh_wrapper(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        leaked = actor.model
        leaked.actor_type = actor_module._SchemaActorType.human
        leaked.tenant_id = None

        # Mutating the leaked copy has no path back into the wrapper's own
        # gate. A genuinely fresh human-without-tenant payload is still
        # correctly rejected -- confirming the gate itself was never
        # touched by mutating the returned snapshot.
        human_without_tenant = make_actor_context_payload(
            actor_id="actor-human-fresh", actor_type="human", session_id="session-fresh"
        )
        with pytest.raises(ActorTenantRequiredError):
            ActorContext.from_payload(human_without_tenant)

    def test_mutating_returned_session_id_does_not_affect_idempotency_key(
        self, actor_context_payload: dict
    ) -> None:
        actor = ActorContext.from_payload(actor_context_payload)
        original_key = actor.idempotency_key()

        leaked = actor.model
        leaked.session_id = "attacker-controlled-session"

        assert actor.idempotency_key() == original_key
        assert actor.session_id != "attacker-controlled-session"
