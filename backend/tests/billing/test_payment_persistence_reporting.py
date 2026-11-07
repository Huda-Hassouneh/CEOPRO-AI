"""Offline reporting checks; these do not execute migration or database proofs."""
import ast
import json
from pathlib import Path

from scripts.verify_payment_persistence import migration_verification_scope


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "verify_payment_persistence.py"


def test_full_restricted_runner_has_no_invented_result():
    report = migration_verification_scope()
    check = report["full_restricted_runner"]
    assert check["execution"] == "NOT_EXECUTED"
    assert check["result"] is None
    assert check["merge_gate"] == "UNVERIFIED"
    assert "source-inferred" in check["note"]
    assert "not a reproduced failure" in check["note"]
    assert "FORCE RLS" in check["note"]
    assert "BLOCKED" not in json.dumps(report)
    assert "FAIL" not in json.dumps(report)


def test_fixture_authority_does_not_claim_production_least_privilege():
    authority = migration_verification_scope()["installer_fixture_authority"]
    assert authority["authentication"] == "password"
    assert authority["superuser"] is False
    assert authority["bypassrls"] is False
    assert authority["createrole"] is True
    assert authority["ownership"] == "public schema and existing public tables"
    assert authority["temporary_membership"] == "ceopro_trial_issuer: SET TRUE, INHERIT FALSE"
    assert authority["explicit_execute"] == [
        "billing_standard_catalog_install(jsonb,text,boolean)",
        "billing_catalog_reconcile()",
    ]
    assert authority["production_least_privilege_verified"] is False


def test_unexecuted_scope_does_not_prepopulate_passing_migration_checks():
    report = migration_verification_scope()
    for name in ("fresh_installation", "populated_upgrade", "restricted_new_migrations"):
        assert name not in report
    # Reports must be independent between invocations.
    report["full_restricted_runner"]["result"] = "PASS"
    assert migration_verification_scope()["full_restricted_runner"]["result"] is None


def test_main_keeps_completed_scopes_distinct_and_full_runner_unexecuted():
    # Inspect reporting statements without invoking Docker or connecting to a DB.
    tree = ast.parse(SOURCE.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    updates = [node for node in ast.walk(main) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and isinstance(node.func.value, ast.Name)
               and node.func.value.id == "report" and node.func.attr == "update"]
    reported = {keyword.arg: keyword.value for node in updates for keyword in node.keywords}
    assert "full_restricted_runner" not in reported
    for name in ("populated_upgrade", "restricted_new_migrations"):
        fields = dict(zip((key.value for key in reported[name].keys), reported[name].values))
        assert ast.literal_eval(fields["execution"]) == "EXECUTED"
        assert ast.literal_eval(fields["result"]) == "PASS"
    assignments = [node for node in ast.walk(main) if isinstance(node, ast.Assign)]
    keys = {target.slice.value: node.value for node in assignments for target in node.targets
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
            and target.value.id == "report" and isinstance(target.slice, ast.Constant)}
    assert "full_restricted_runner" not in keys
    fresh = ast.literal_eval(keys["fresh_installation"])
    assert fresh == {"execution": "EXECUTED", "result": "PASS",
                     "authority": "postgres superuser; full runner and replay"}
    statuses = [ast.literal_eval(node.value) for node in assignments for target in node.targets
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                and target.value.id == "report" and isinstance(target.slice, ast.Constant)
                and target.slice.value == "status"]
    assert "executed_checks_passed" in statuses
    assert "passed" not in statuses
