from pathlib import Path


def test_platform_billing_contract_read_uses_existing_contract_timestamps():
    migration = (
        Path(__file__).parents[2]
        / "infrastructure"
        / "database"
        / "migrations"
        / "20261103000300_platform_contract_billing_read_fix.sql"
    ).read_text(encoding="utf-8")
    contracts = migration.split("ELSIF p_action='contracts' THEN", 1)[1].split(
        "ELSIF p_action='audit' THEN", 1
    )[0]

    assert "cc.approved_at" in contracts
    assert "cc.created_at" not in contracts
    assert "ORDER BY x.approved_at DESC NULLS LAST" in contracts
