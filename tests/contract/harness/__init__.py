"""Contract compatibility harness (W1, ADR-0012 §Harness 소유권 분리).

testing/QA is the single implementation owner of contract compatibility
judgment code (ADR-0012: "harness 이원 구현 금지"). The Contracts Steward
owns the judgment *rules* (ADR-0012), `packages/contracts/registry.json`
content, and git tag issuance (ADR-0011); this package mechanically
enforces those rules — it does not invent new ones.

Modules:
  - registry: load + validate packages/contracts/registry.json against
    registry.schema.json, plus relational checks not expressible in JSON
    Schema (name+major uniqueness, full_version/major-prefix agreement,
    $id path/category consistency, on-disk schema-file existence).
  - tags: git-tag discovery/sort (`contracts/{name}/v*`, tests/contract/
    README.md "Tag scheme"), previous-tag resolution, tag-scoped file
    reads (`git show <tag>:<path>`).
  - diff: structural_diff() (moved from test_compat_selfdiff.py, W0) plus
    W1 extensions — items recursion, within-file $ref resolution, const
    change detection, cross-file $ref string comparison, pattern-change
    detection (ruling R5).
  - rules: judge() — the closed/open/frozen verdict function (ADR-0012).
  - util: fixture-metadata stripping + tempfile helpers (promoted from
    test_envelope_fixtures.py's _strip_metadata_to_tempfile pattern,
    tests/contract/README.md "Fixture metadata convention").
"""

from __future__ import annotations
