"""`TestEmbedder` — deterministic, seeded, fully OFFLINE embedder (w4-07).

Embedding PROVIDER selection is an OPEN decision (w4-07 task brief: "record
as production-only") — this package deliberately ships NO production
embedding-provider integration and never calls out to any external API. The
ONLY embedder in this package is `TestEmbedder`, used exclusively by this
package's own tests (and available to any caller's tests) so that neither
the unit lane nor the `tests/integration/vector/**` real-Postgres lane ever
depends on network access or an external embedding provider's credentials/
availability/cost.

Determinism: `embed_vector(text)` is a pure function of
`(seed, model, version, dimension, text)` — same inputs always produce the
exact same output, on any machine, with no random state, no clock, and no
I/O. Implemented via `hashlib.sha256` (stdlib only — no `numpy`/`torch`/
etc. dependency) seeded per output dimension, then L2-normalized (pure
`math`, no `numpy`) so ANN distance comparisons between two `TestEmbedder`
outputs are stable and meaningful (all vectors lie on the unit hypersphere,
matching how a real embedding model's cosine-comparable output typically
behaves) rather than comparing raw, unnormalized hash-derived floats.
"""

from __future__ import annotations

import hashlib
import math
import struct

from saena_vector_store.record import EmbeddingMeta

DEFAULT_MODEL = "saena-test-embedder"
DEFAULT_VERSION = "1.0.0"


class TestEmbedder:
    """Deterministic, seeded, offline stand-in embedder.

    NEVER calls a network socket, external process, or real embedding
    provider — `embed_vector` is pure in-process hashing + normalization.
    """

    # Not a pytest test class — its name only coincidentally matches
    # pytest's default `Test*` collection pattern (it IS the "embedder used
    # by tests" this package ships, not a test itself). `__test__ = False`
    # silences the resulting `PytestCollectionWarning` at every call site
    # that imports it, rather than requiring every test module to suppress
    # it individually.
    __test__ = False

    def __init__(
        self,
        *,
        dimension: int = 8,
        seed: int = 0,
        model: str = DEFAULT_MODEL,
        version: str = DEFAULT_VERSION,
    ) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be a positive integer, got {dimension!r}")
        self._dimension = dimension
        self._seed = seed
        self._model = model
        self._version = version

    @property
    def dimension(self) -> int:
        return self._dimension

    def embedding_meta(self) -> EmbeddingMeta:
        """The `EmbeddingMeta` every vector produced by this embedder instance carries."""
        return EmbeddingMeta(model=self._model, version=self._version, dimension=self._dimension)

    def embed_vector(self, text: str) -> tuple[float, ...]:
        """Deterministically derive a unit-length `self.dimension`-vector from `text`.

        Same `(seed, model, version, dimension, text)` -> byte-identical
        output, every call, forever — no randomness, no I/O.
        """
        raw = [self._hash_component(text, i) for i in range(self._dimension)]
        norm = math.sqrt(sum(component * component for component in raw))
        if norm == 0.0:
            # Astronomically unlikely for sha256-derived floats, but keep the
            # output well-defined (a unit vector along the first axis)
            # rather than dividing by zero.
            return tuple(1.0 if i == 0 else 0.0 for i in range(self._dimension))
        return tuple(component / norm for component in raw)

    def _hash_component(self, text: str, index: int) -> float:
        """One raw (pre-normalization) float component, derived from a
        SHA-256 digest of `(seed, model, version, text, index)` — stdlib
        `hashlib`/`struct` only, no external randomness source."""
        digest = hashlib.sha256(
            f"{self._seed}:{self._model}:{self._version}:{index}:{text}".encode()
        ).digest()
        (raw_uint,) = struct.unpack(">Q", digest[:8])
        # Map the full unsigned 64-bit range onto [-1.0, 1.0].
        return (raw_uint / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


__all__ = ["DEFAULT_MODEL", "DEFAULT_VERSION", "TestEmbedder"]
