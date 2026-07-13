"""Unit tests: `saena_entity_resolution.canonicalize` — alias-merge,
determinism, and the fail-closed ownership rule."""

from __future__ import annotations

import pytest
from saena_entity_resolution.canonicalize import (
    AliasGroup,
    EntityType,
    compute_graph_version,
    resolve_entities,
)
from saena_entity_resolution.errors import (
    AliasConflictError,
    CompetitorOwnershipDeniedError,
    EmptyAliasSetError,
)


def _brand_group(**overrides: object) -> AliasGroup:
    defaults: dict[str, object] = {
        "entity_id": "e-brand-1",
        "entity_type": EntityType.brand,
        "canonical_name": "Acme",
        "aliases": ("Acme Inc", "acme", "ACME"),
        "is_owned": True,
    }
    defaults.update(overrides)
    return AliasGroup(**defaults)  # type: ignore[arg-type]


def _competitor_group(**overrides: object) -> AliasGroup:
    defaults: dict[str, object] = {
        "entity_id": "e-comp-1",
        "entity_type": EntityType.competitor,
        "canonical_name": "Rival Co",
        "aliases": ("rival", "Rival Corp"),
        "is_owned": False,
    }
    defaults.update(overrides)
    return AliasGroup(**defaults)  # type: ignore[arg-type]


class TestAliasMerging:
    def test_alias_group_resolves_to_single_canonical_record(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[_brand_group()]
        )
        assert len(result.entities) == 1
        record = result.entities[0]
        assert record.entity_id == "e-brand-1"
        assert record.canonical_name == "Acme"
        assert record.entity_type == EntityType.brand

    def test_multiple_alias_groups_each_resolve_to_one_record(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=[_brand_group(), _competitor_group()],
        )
        assert len(result.entities) == 2
        entity_ids = {record.entity_id for record in result.entities}
        assert entity_ids == {"e-brand-1", "e-comp-1"}

    def test_all_entities_share_the_same_graph_version(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=[_brand_group(), _competitor_group()],
        )
        versions = {record.graph_version for record in result.entities}
        assert versions == {result.graph_version}

    def test_entity_record_carries_tenant_and_project_scope(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp", project_id="proj-42", alias_groups=[_brand_group()]
        )
        record = result.entities[0]
        assert record.tenant_id.root == "acme-corp"
        assert record.project_id.root == "proj-42"

    def test_alias_casing_and_whitespace_are_normalized(self) -> None:
        # Two groups whose alias *sets* differ only by case/whitespace must
        # not raise a cross-group conflict against themselves — this checks
        # normalization happens before conflict detection, not that it
        # merges across groups (merging across groups happens only via a
        # shared entity_id, never via alias-string equality alone).
        group = _brand_group(aliases=("  Acme  ", "ACME", "acme"))
        result = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=[group])
        assert len(result.entities) == 1


class TestDeterminism:
    def test_identical_input_produces_byte_identical_graph_version(self) -> None:
        groups = [_brand_group(), _competitor_group()]
        result_a = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=groups)
        result_b = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=groups)
        assert result_a.graph_version == result_b.graph_version

    def test_graph_version_independent_of_alias_group_order(self) -> None:
        brand, competitor = _brand_group(), _competitor_group()
        forward = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[brand, competitor]
        )
        reversed_ = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[competitor, brand]
        )
        assert forward.graph_version == reversed_.graph_version

    def test_graph_version_independent_of_within_group_alias_order(self) -> None:
        group_a = _brand_group(aliases=("Acme Inc", "acme", "ACME"))
        group_b = _brand_group(aliases=("ACME", "Acme Inc", "acme"))
        result_a = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[group_a]
        )
        result_b = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[group_b]
        )
        assert result_a.graph_version == result_b.graph_version

    def test_graph_version_independent_of_updated_at_clock(self) -> None:
        groups = [_brand_group()]
        result_a = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=groups,
            clock=lambda: "2020-01-01T00:00:00Z",
        )
        result_b = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=groups,
            clock=lambda: "2030-06-15T12:00:00Z",
        )
        assert result_a.graph_version == result_b.graph_version
        assert result_a.entities[0].updated_at != result_b.entities[0].updated_at

    def test_different_canonical_name_changes_graph_version(self) -> None:
        result_a = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[_brand_group()]
        )
        result_b = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=[_brand_group(canonical_name="Acme Corp Global")],
        )
        assert result_a.graph_version != result_b.graph_version

    def test_different_tenant_changes_graph_version(self) -> None:
        groups = [_brand_group()]
        result_a = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=groups)
        result_b = resolve_entities(
            tenant_id="other-corp", project_id="proj-1", alias_groups=groups
        )
        assert result_a.graph_version != result_b.graph_version

    def test_graph_version_has_sha256_wire_form(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[_brand_group()]
        )
        assert result.graph_version.startswith("sha256:")
        assert len(result.graph_version) == len("sha256:") + 64

    def test_compute_graph_version_matches_resolve_entities(self) -> None:
        groups = [_brand_group(), _competitor_group()]
        result = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=groups)
        recomputed = compute_graph_version("acme-corp", "proj-1", groups)
        assert recomputed == result.graph_version


class TestOwnershipRule:
    def test_competitor_marked_owned_is_refused(self) -> None:
        with pytest.raises(CompetitorOwnershipDeniedError):
            resolve_entities(
                tenant_id="acme-corp",
                project_id="proj-1",
                alias_groups=[_competitor_group(is_owned=True)],
            )

    def test_competitor_not_owned_is_permitted(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=[_competitor_group(is_owned=False)],
        )
        assert result.entities[0].entity_type == EntityType.competitor

    def test_brand_marked_owned_is_permitted(self) -> None:
        result = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[_brand_group(is_owned=True)]
        )
        assert result.entities[0].entity_type == EntityType.brand

    def test_ownership_rule_has_no_bypass_parameter(self) -> None:
        # Regression pin: `resolve_entities`/`AliasGroup` must never grow a
        # force/override/bypass-shaped parameter that could defeat the
        # ownership gate (CLAUDE.md operating principle 3 / w3-14 "no
        # opt-out" precedent).
        import inspect

        from saena_entity_resolution.canonicalize import AliasGroup as _AG
        from saena_entity_resolution.canonicalize import resolve_entities as _resolve

        forbidden_tokens = ("force", "bypass", "override", "skip", "allow_owned")
        for fn in (_resolve, _AG):
            params = inspect.signature(fn).parameters
            for name in params:
                lowered = name.lower()
                assert not any(token in lowered for token in forbidden_tokens), name

    def test_ownership_denial_error_names_the_offending_entity(self) -> None:
        with pytest.raises(CompetitorOwnershipDeniedError) as excinfo:
            resolve_entities(
                tenant_id="acme-corp",
                project_id="proj-1",
                alias_groups=[_competitor_group(entity_id="e-comp-99", is_owned=True)],
            )
        assert excinfo.value.context["entity_id"] == "e-comp-99"

    def test_ownership_denial_checked_even_with_other_valid_groups(self) -> None:
        with pytest.raises(CompetitorOwnershipDeniedError):
            resolve_entities(
                tenant_id="acme-corp",
                project_id="proj-1",
                alias_groups=[_brand_group(), _competitor_group(is_owned=True)],
            )


class TestValidationFailureBranches:
    def test_empty_alias_set_is_rejected(self) -> None:
        with pytest.raises(EmptyAliasSetError):
            resolve_entities(
                tenant_id="acme-corp",
                project_id="proj-1",
                alias_groups=[_brand_group(aliases=())],
            )

    def test_whitespace_only_aliases_are_rejected(self) -> None:
        with pytest.raises(EmptyAliasSetError):
            resolve_entities(
                tenant_id="acme-corp",
                project_id="proj-1",
                alias_groups=[_brand_group(aliases=("   ", ""))],
            )

    def test_duplicate_entity_id_with_conflicting_attributes_is_rejected(self) -> None:
        group_a = _brand_group(entity_id="dup-1", canonical_name="Acme")
        group_b = _brand_group(entity_id="dup-1", canonical_name="Different Name")
        with pytest.raises(AliasConflictError):
            resolve_entities(
                tenant_id="acme-corp", project_id="proj-1", alias_groups=[group_a, group_b]
            )

    def test_duplicate_entity_id_with_identical_attributes_is_not_an_error(self) -> None:
        # Byte-identical re-declaration of the SAME entity is not a
        # conflict (idempotent-shaped input); it just resolves to one record
        # in the deduplicated identity space captured by entity_id.
        group = _brand_group(entity_id="dup-2")
        result = resolve_entities(
            tenant_id="acme-corp", project_id="proj-1", alias_groups=[group, group]
        )
        # Two AliasGroup entries with the same entity_id both survive into
        # `entities` (this module does not silently drop caller-supplied
        # groups); the point under test is that no AliasConflictError fires.
        assert all(record.entity_id == "dup-2" for record in result.entities)

    def test_same_alias_claimed_by_two_different_entities_is_rejected(self) -> None:
        group_a = _brand_group(entity_id="e-a", aliases=("shared-alias",))
        group_b = _competitor_group(entity_id="e-b", aliases=("shared-alias",))
        with pytest.raises(AliasConflictError):
            resolve_entities(
                tenant_id="acme-corp", project_id="proj-1", alias_groups=[group_a, group_b]
            )

    def test_no_alias_groups_resolves_to_empty_graph(self) -> None:
        result = resolve_entities(tenant_id="acme-corp", project_id="proj-1", alias_groups=[])
        assert result.entities == ()
        assert result.graph_version.startswith("sha256:")
