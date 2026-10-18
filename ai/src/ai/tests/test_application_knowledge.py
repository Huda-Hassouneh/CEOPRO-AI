"""
Tests for src/ai/knowledge/application_registry.py and
scripts/validate_application_knowledge.py.

No live DB, no LLM - this is pure Python data plus file-existence/import
checks, so these run everywhere (unlike the live-DB integration tests in
this same directory).
"""
import dataclasses
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

# These are only here so importing the modules below doesn't crash when
# nothing has configured a real DB/JWT env yet. Set with plain os.environ
# (not setdefault) and torn back down right after the import: setdefault
# would otherwise leak a fake "APP_DB_PASSWORD"/"DATABASE_URL" into the rest
# of the process for the whole pytest run, since these are the exact env
# vars test_rls_integration_db.py/test_conversation_store_integration_db.py
# check for at their own module import time to decide whether to attempt a
# real DB connection or skip - a leaked placeholder value turns their honest
# skip into a spurious "password authentication failed" test failure.
_PLACEHOLDER_ENV = {
    "JWT_SECRET": "test-secret",
    "DATABASE_URL": "postgresql://placeholder:placeholder@localhost:5432/placeholder",
    "APP_DB_PASSWORD": "placeholder",
}
_added_placeholder_keys = [key for key in _PLACEHOLDER_ENV if key not in os.environ]
os.environ.update({key: _PLACEHOLDER_ENV[key] for key in _added_placeholder_keys})

from src.ai.knowledge.application_registry import (  # noqa: E402
    APPLICATION_FEATURES,
    get_feature,
    search_features,
)

import scripts.validate_application_knowledge as validator  # noqa: E402

for _key in _added_placeholder_keys:
    del os.environ[_key]


def test_registry_is_non_empty():
    assert len(APPLICATION_FEATURES) >= 10


def test_every_feature_has_required_identity_fields():
    seen_ids = set()
    for feature in APPLICATION_FEATURES:
        assert feature.feature_id, "feature_id must not be empty"
        assert feature.feature_id not in seen_ids, f"duplicate feature_id: {feature.feature_id}"
        seen_ids.add(feature.feature_id)
        assert feature.name
        assert feature.page
        assert feature.action
        assert feature.action_steps, f"{feature.feature_id} has no action_steps"
        assert feature.source_commit
        assert feature.last_synchronized


def test_get_feature_returns_none_for_unknown_id():
    assert get_feature("this_feature_does_not_exist") is None


def test_get_feature_returns_real_entry():
    feature = get_feature("add_product")
    assert feature is not None
    assert feature.route == "/products/new"


def test_search_features_finds_add_product_by_keyword():
    results = search_features("how do I add a new product")
    ids = [f.feature_id for f in results]
    assert "add_product" in ids


def test_search_features_empty_query_returns_nothing():
    assert search_features("") == []
    assert search_features(None) == []


def test_search_features_does_not_match_unrelated_question():
    results = search_features("xyzzy plugh quux")
    assert results == []


def test_validator_passes_against_the_real_current_repository():
    """The real assertion this whole file exists for: the registry is
    not stale right now, against the actual repo this test runs in."""
    problems = validator.validate()
    assert problems == [], f"Application Knowledge Registry is stale: {problems}"


def test_validator_detects_a_renamed_route():
    """Proves the validator isn't a no-op - simulates a route rename the
    registry wasn't updated for, on an in-memory copy only (never
    mutates the real APPLICATION_FEATURES list)."""
    fake_features = list(APPLICATION_FEATURES)
    fake_features[0] = dataclasses.replace(fake_features[0], route="/this/route/does/not/exist")

    original = validator.APPLICATION_FEATURES
    try:
        validator.APPLICATION_FEATURES = fake_features
        problems = validator.validate()
    finally:
        validator.APPLICATION_FEATURES = original

    assert len(problems) == 1
    assert "not found in routePaths.js" in problems[0]


def test_validator_detects_a_missing_frontend_file():
    fake_features = list(APPLICATION_FEATURES)
    fake_features[0] = dataclasses.replace(fake_features[0], frontend_source_file="frontend/src/does/not/exist.jsx")

    original = validator.APPLICATION_FEATURES
    try:
        validator.APPLICATION_FEATURES = fake_features
        problems = validator.validate()
    finally:
        validator.APPLICATION_FEATURES = original

    assert any("does not exist on disk" in p for p in problems)
