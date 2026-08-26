from unittest.mock import MagicMock, patch

from src.ai.extraction.extractor import extract_entities


def test_extract_entities_without_catalogs_still_runs_regex():
    text = "Invoice INV-1001 for 18.00 JOD dated 2026-07-27"
    entities = extract_entities(text)
    types = {e.entity_type for e in entities}
    assert "INVOICE_ID" in types
    assert "MONEY" in types
    assert "DATE" in types


def test_extract_entities_includes_catalog_matches_when_provided():
    text = "Sunscreen SPF 50 is priced at 18.00 JOD, ahead of Rival Pharmacy"
    with patch(
        "src.ai.extraction.extractor.get_known_names",
        side_effect=lambda redis_client, conn, tenant_id, entity_kind: (
            ["Sunscreen SPF 50"] if entity_kind == "products" else ["Rival Pharmacy"]
        ),
    ):
        entities = extract_entities(text, tenant_id="tenant-1", redis_client=MagicMock(), conn=MagicMock())
    types = {e.entity_type for e in entities}
    assert "PRODUCT" in types
    assert "COMPETITOR" in types
    assert "MONEY" in types


def test_extract_entities_sorted_by_position():
    text = "Rival Pharmacy sells Sunscreen SPF 50 for 18.00 JOD"
    with patch(
        "src.ai.extraction.extractor.get_known_names",
        side_effect=lambda redis_client, conn, tenant_id, entity_kind: (
            ["Sunscreen SPF 50"] if entity_kind == "products" else ["Rival Pharmacy"]
        ),
    ):
        entities = extract_entities(text, tenant_id="tenant-1", redis_client=MagicMock(), conn=MagicMock())
    assert all(entities[i].start <= entities[i + 1].start for i in range(len(entities) - 1))


def test_extract_entities_skips_catalog_matching_when_dependencies_missing():
    """tenant_id/redis_client/conn must ALL be supplied - partial args silently skip catalog matching."""
    text = "Sunscreen SPF 50 for 18.00 JOD"
    with patch("src.ai.extraction.extractor.get_known_names") as mock_get_names:
        entities = extract_entities(text, tenant_id="tenant-1")
    mock_get_names.assert_not_called()
    types = {e.entity_type for e in entities}
    assert "PRODUCT" not in types
    assert "MONEY" in types
