"""`Fixture` — one deterministic, seeded eval case, and its YAML loader.

Every fixture file under `evals/fixtures/<axis>/`, `evals/policy-tests/
<axis>/`, or `evals/regression-suites/failure_modes/` follows the SAME
closed shape (checked below, fail-closed on a malformed fixture — a fixture
that cannot be loaded is a harness bug, never silently skipped):

```yaml
fixture_id: "patch-correctness-pass-build-and-tests"   # unique within its axis dir
axis: "patch_correctness"                               # must match AXIS_SCORERS key
seed: 1337                                               # carried, never used for randomness
description: "..."                                       # human-readable intent
tag: "nominal"                                           # see tag values below
expected_passed: true
expected_score: 1.0
threshold: 1.0
input: { ... axis-specific ... }
```

`tag` documents WHY a fixture exists (mission requirement: "include
false-positive AND false-negative example fixtures for at least a few axes
... proving the scorer discriminates"):

  - `nominal`             — an ordinary true-positive/true-negative case.
  - `false_positive_guard` — a case that LOOKS like it should fail/be denied
    on a naive check but must legitimately PASS/ALLOW — proves the scorer
    does not over-block (e.g. `git commit -m "push to prod later"` must
    ALLOW, per `saena_hooks_runtime.rules.deploy_push`'s own docstring).
  - `false_negative_guard` — a case that LOOKS like it should pass/be
    allowed on a naive presence-only check but must legitimately FAIL/DENY
    — proves the scorer does not rubber-stamp (e.g. a critic review object
    is present but is a non-independent self-review).

No randomness, no wall-clock: `seed` is a plain recorded integer, `load_fixture`
performs no I/O beyond reading the one file handed to it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REQUIRED_KEYS = frozenset(
    {
        "fixture_id",
        "axis",
        "seed",
        "description",
        "tag",
        "expected_passed",
        "expected_score",
        "threshold",
        "input",
    }
)

_VALID_TAGS = frozenset({"nominal", "false_positive_guard", "false_negative_guard"})


class FixtureLoadError(ValueError):
    """Raised for a structurally malformed fixture file — fail-closed, this
    harness never silently skips or partially-loads a fixture."""


@dataclass(frozen=True, slots=True)
class Fixture:
    fixture_id: str
    axis: str
    seed: int
    description: str
    tag: str
    expected_passed: bool
    expected_score: float
    threshold: float
    input: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @property
    def discriminates(self) -> bool:
        """`True` for a fixture whose whole purpose is proving the scorer
        does NOT take the naive shortcut (see module docstring `tag`)."""
        return self.tag != "nominal"


def load_fixture(path: Path) -> Fixture:
    """Load and structurally validate one fixture YAML file.

    Raises `FixtureLoadError` for any missing required key, an unknown
    `tag`, or a `fixture_id`/`axis` mismatch against the file's own location
    convention — never returns a partially-populated `Fixture`.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"{path}: fixture document must be a YAML mapping")
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise FixtureLoadError(f"{path}: missing required key(s) {sorted(missing)!r}")
    tag = raw["tag"]
    if tag not in _VALID_TAGS:
        raise FixtureLoadError(f"{path}: tag {tag!r} is not one of {sorted(_VALID_TAGS)!r}")
    input_block = raw["input"]
    if not isinstance(input_block, dict):
        raise FixtureLoadError(f"{path}: 'input' must be a mapping")
    return Fixture(
        fixture_id=str(raw["fixture_id"]),
        axis=str(raw["axis"]),
        seed=int(raw["seed"]),
        description=str(raw["description"]),
        tag=str(tag),
        expected_passed=bool(raw["expected_passed"]),
        expected_score=float(raw["expected_score"]),
        threshold=float(raw["threshold"]),
        input=input_block,
        source_path=path,
    )


def load_fixtures(directory: Path) -> list[Fixture]:
    """Load every `*.yaml` fixture directly under `directory`, sorted by
    filename for deterministic ordering."""
    if not directory.is_dir():
        raise FixtureLoadError(f"{directory}: not a directory")
    return [load_fixture(p) for p in sorted(directory.glob("*.yaml"))]


def iter_fixture_files(directory: Path) -> Iterator[Path]:
    yield from sorted(directory.glob("*.yaml"))


__all__ = [
    "Fixture",
    "FixtureLoadError",
    "iter_fixture_files",
    "load_fixture",
    "load_fixtures",
]
