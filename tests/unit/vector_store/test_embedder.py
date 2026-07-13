"""`TestEmbedder` determinism/offline guarantees (w4-07)."""

from __future__ import annotations

import math

import pytest
from saena_vector_store.embedder import TestEmbedder


def test_same_inputs_produce_byte_identical_output() -> None:
    a = TestEmbedder(dimension=8, seed=42).embed_vector("hello world")
    b = TestEmbedder(dimension=8, seed=42).embed_vector("hello world")
    assert a == b


def test_different_seed_produces_different_output() -> None:
    a = TestEmbedder(dimension=8, seed=1).embed_vector("hello world")
    b = TestEmbedder(dimension=8, seed=2).embed_vector("hello world")
    assert a != b


def test_different_text_produces_different_output() -> None:
    embedder = TestEmbedder(dimension=8, seed=0)
    assert embedder.embed_vector("alpha") != embedder.embed_vector("beta")


def test_output_is_unit_length() -> None:
    vector = TestEmbedder(dimension=16, seed=7).embed_vector("some text")
    norm = math.sqrt(sum(component * component for component in vector))
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_output_dimension_matches_configured_dimension() -> None:
    embedder = TestEmbedder(dimension=12, seed=0)
    assert len(embedder.embed_vector("x")) == 12
    assert embedder.dimension == 12


def test_embedding_meta_matches_configured_model_version_dimension() -> None:
    embedder = TestEmbedder(dimension=5, seed=0, model="custom-model", version="2.3.4")
    meta = embedder.embedding_meta()
    assert meta.model == "custom-model"
    assert meta.version == "2.3.4"
    assert meta.dimension == 5


def test_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError):
        TestEmbedder(dimension=0)
    with pytest.raises(ValueError):
        TestEmbedder(dimension=-3)
