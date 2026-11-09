"""Keep managed catalog isolation explicit in the CI job."""
from urllib.parse import urlsplit
from .test_pr_ci_contract import BACKEND, value


def test_managed_installers_have_independent_empty_ci_clusters():
    primary = urlsplit(value("AI_TEST_MANAGED_PG_ADMIN_URL"))
    reference = urlsplit(value("AI_TEST_MANAGED_PG_SUPER_ADMIN_URL"))
    assert primary.hostname == reference.hostname == "127.0.0.1"
    assert primary.path == reference.path == "/postgres"
    assert primary.port == 5433 and reference.port == 5434
    assert "postgres_managed_super:" in BACKEND and "- 5434:5432" in BACKEND
    assert BACKEND.count("image: pgvector/pgvector:pg17") >= 3
