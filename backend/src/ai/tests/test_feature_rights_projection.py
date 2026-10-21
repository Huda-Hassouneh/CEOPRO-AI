import ast
import csv
from copy import deepcopy
from pathlib import Path

import pytest

from src.ai.core import feature_rights


ROOT = Path(__file__).resolve().parents[4]
CROSSWALK = ROOT / "docs" / "keel-integration" / "FEATURE_AND_ENTITLEMENT_CROSSWALK.csv"
USAGE_SOURCE = ROOT / "backend" / "src" / "ai" / "core" / "usage.py"


def _plan(**overrides):
    plan = {
        "plan_key": "growth",
        "status": "active",
        "assigned": True,
        "source": "stripe",
        "period_code": "monthly",
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "trial_ends_at": None,
        "features": {
            "tracked_products": {"unit": "products", "aggregation_type": "max", "reset_cycle": "lifetime", "limit": None},
            "tracked_competitors": {"unit": "competitors", "aggregation_type": "max", "reset_cycle": "lifetime", "limit": 0},
            "rag_assistant": {"unit": "tokens", "aggregation_type": "sum", "reset_cycle": "billing_period", "limit": 25},
            "monthly_reports": {"unit": "reports", "aggregation_type": "sum", "reset_cycle": "billing_period", "limit": 4},
            "team_seats": {"unit": "seats", "aggregation_type": "max", "reset_cycle": "lifetime", "limit": 3},
            "ai_credits": {"unit": "credits", "aggregation_type": "sum", "reset_cycle": "billing_period", "limit": 10},
            "data_credits": {"unit": "credits", "aggregation_type": "sum", "reset_cycle": "billing_period", "limit": 12},
            "web_searches": {"unit": "searches", "aggregation_type": "sum", "reset_cycle": "billing_period", "limit": 8},
        },
        "entitlements": ["market_intelligence", "competitor_management"],
    }
    plan.update(overrides)
    return plan


def _right(projection, code):
    return next(item for item in projection["rights"] if item["feature_code"] == code)


def test_projection_registry_covers_authoritative_crosswalk_without_inventing_targets():
    with CROSSWALK.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    actual = {item.feature_code: item for item in feature_rights.FEATURE_MAPPINGS}
    node_rows = [row for row in rows if row["node_feature_code"] != "NONE"]
    python_only_rows = [row for row in rows if row["node_feature_code"] == "NONE"]
    assert len(node_rows) == 21
    assert len(python_only_rows) == 3
    assert len(actual) == len(feature_rights.FEATURE_MAPPINGS)
    assert set(actual) == {
        row["node_feature_code"] if row["node_feature_code"] != "NONE"
        else row["python_feature_code"]
        for row in rows
    }

    for row in rows:
        code = row["node_feature_code"] if row["node_feature_code"] != "NONE" else row["python_feature_code"]
        item = actual[code]
        assert item.status == row["b1_mapping_status"]
        if item.status == "unmapped":
            assert item.python_feature_code is None
        else:
            expected_python_code = row["python_feature_code"].split(" [", 1)[0]
            assert item.python_feature_code == expected_python_code


def test_established_targets_are_existing_python_feature_or_module_codes():
    tree = ast.parse(USAGE_SOURCE.read_text(encoding="utf-8"))
    python_codes = set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Constant):
            continue
        if not isinstance(statement.value.value, str):
            continue
        if any(isinstance(target, ast.Name) and target.id.isupper() for target in statement.targets):
            python_codes.add(statement.value.value)

    for item in feature_rights.FEATURE_MAPPINGS:
        if item.status in ("established_python_code", "candidate_alias"):
            assert item.python_feature_code in python_codes


def test_limited_zero_unlimited_absent_and_boolean_states_stay_distinct():
    projection = feature_rights.project_effective_rights(_plan())

    assert _right(projection, "rag_assistant")["configured_state"] == "limited"
    assert _right(projection, "rag_assistant")["limit"] == 25
    assert _right(projection, "tracked_competitors")["configured_state"] == "explicit_zero"
    assert _right(projection, "tracked_competitors")["limit"] == 0
    assert _right(projection, "tracked_products")["configured_state"] == "unlimited"
    assert _right(projection, "tracked_products")["limit"] is None
    assert _right(projection, "sentiment_analysis")["configured_state"] == "absent"
    assert _right(projection, "market_intelligence")["configured_state"] == "enabled"
    assert _right(projection, "demand_prediction")["configured_state"] == "disabled"


def test_missing_boolean_entitlement_collection_is_absent_not_disabled():
    plan = _plan()
    del plan["entitlements"]

    projection = feature_rights.project_effective_rights(plan)

    assert _right(projection, "market_intelligence")["configured_state"] == "absent"
    assert _right(projection, "market_intelligence")["is_configured"] is False


def test_candidate_aliases_show_python_evidence_without_granting_aliases():
    projection = feature_rights.project_effective_rights(_plan())

    report = _right(projection, "report_generation")
    assert report["mapping_status"] == "candidate_alias"
    assert report["configured_state"] == "unmapped"
    assert report["is_configured"] is False
    assert report["candidate_python_state"] == "limited"

    perception = _right(projection, "market_perception")
    assert perception["configured_state"] == "unmapped"
    assert perception["candidate_python_state"] == "enabled"


def test_unmapped_codes_never_become_grants():
    projection = feature_rights.project_effective_rights(_plan())
    for code in (
        "dashboard_analytics", "inventory_intelligence", "product_management",
        "data_integration", "business_recommendations", "system_alerts", "ai_pricing",
    ):
        right = _right(projection, code)
        assert right["python_feature_code"] is None
        assert right["mapping_status"] == "unmapped"
        assert right["configured_state"] == "unmapped"
        assert right["is_configured"] is False


def test_public_private_trial_and_unassigned_plan_context_is_preserved():
    public = feature_rights.project_effective_rights(
        _plan(plan_key="starter", status="active", source="stripe")
    )
    assert public["plan_key"] == "starter"
    assert public["status"] == "active"

    trial = _plan(
        plan_key="private_custom", status="trialing", assigned=True, source="contract",
        period_code="yearly", trial_ends_at="2026-10-25T00:00:00+00:00",
    )
    trial_view = feature_rights.project_effective_rights(trial)
    assert trial_view["plan_key"] == "private_custom"
    assert trial_view["status"] == "trialing"
    assert trial_view["source"] == "contract"
    assert trial_view["period_code"] == "yearly"
    assert trial_view["trial_ends_at"] == "2026-10-25T00:00:00+00:00"

    unassigned = _plan(plan_key="growth", status="none", assigned=False, source=None)
    unassigned_view = feature_rights.project_effective_rights(unassigned)
    assert unassigned_view["assigned"] is False
    assert unassigned_view["status"] == "none"
    assert _right(unassigned_view, "rag_assistant")["configured_state"] == "limited"


def test_projection_is_pure_and_does_not_disclose_or_copy_tenant_or_credit_data():
    plan = _plan(tenant_id="tenant-a", credits={"balance": 999})
    original = deepcopy(plan)

    view = feature_rights.project_effective_rights(plan)

    assert plan == original
    assert view["projection_type"] == "informational_only"
    assert "tenant_id" not in view
    assert "credits" not in view
    assert "usage" not in view
    module_tree = ast.parse((ROOT / "backend/src/ai/core/feature_rights.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ("src.ai" in getattr(node, "module", "") or
                    any(alias.name.startswith("src.ai") for alias in getattr(node, "names", [])))
                   for node in ast.walk(module_tree))


def test_invalid_limit_values_are_not_coerced_into_rights():
    for value in (True, -1, 1.5):
        plan = _plan(features={
            "tracked_products": {"unit": "products", "aggregation_type": "max", "reset_cycle": "lifetime", "limit": value}
        })
        with pytest.raises(ValueError):
            feature_rights.project_effective_rights(plan)
