"""
Offline tests for data_access.py's pure pgvector text-literal helpers - no
psycopg2 adapter is used for the `vector` type (see the module docstring),
so this round-trip (Python array -> Postgres literal -> Python array) is
the actual mechanism the persistence fix (audit finding P1) depends on
being correct. DB-touching functions (replace_document_chunks,
load_tenant_chunks, list_documents) are covered by
test_rag_integration.py's live-DB tests instead.
"""

import numpy as np

from src.ai.rag.data_access import _from_pgvector_literal, _to_pgvector_literal


def test_round_trips_a_realistic_384_dim_embedding():
    original = np.random.RandomState(42).normal(size=384).astype(np.float32)
    literal = _to_pgvector_literal(original)
    restored = _from_pgvector_literal(literal)

    assert restored.shape == original.shape
    np.testing.assert_allclose(restored, original, rtol=1e-5)


def test_literal_format_matches_pgvector_bracket_syntax():
    literal = _to_pgvector_literal(np.array([0.1, -0.2, 0.3], dtype=np.float32))
    assert literal.startswith("[")
    assert literal.endswith("]")
    assert literal.count(",") == 2  # 3 values -> 2 separators


def test_negative_and_zero_values_round_trip_correctly():
    original = np.array([0.0, -1.5, 1.5], dtype=np.float32)
    restored = _from_pgvector_literal(_to_pgvector_literal(original))
    np.testing.assert_allclose(restored, original, rtol=1e-6)
