"""
CEOPRO AI - Extraction Evidence Writer.
Writes only to extracted_entity, this track's own table for extraction
output. Never writes to news_record/social_mention's text columns -
pipeline.py separately updates their extraction_status via data_access.py.
"""

from typing import List

from src.ai.extraction.regex_patterns import ExtractedEntity


def insert_extracted_entities(
    conn, tenant_id: str, source_table: str, source_record_id: str, entities: List[ExtractedEntity]
) -> List[str]:
    """
    Persists one source record's extracted entities. entity_value is the
    catalog-normalized name when one exists (PRODUCT/COMPETITOR matches),
    otherwise the raw matched text - mirrors ExtractedEntity.normalized_value's
    own "falls back to text" convention used elsewhere in this module.
    """
    query = """
        INSERT INTO extracted_entity
            (tenant_id, source_table, source_record_id, entity_type, entity_value, confidence_score)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING entity_id;
    """
    entity_ids = []
    with conn.cursor() as cursor:
        for entity in entities:
            entity_value = entity.normalized_value if entity.normalized_value else entity.text
            cursor.execute(
                query,
                (tenant_id, source_table, source_record_id, entity.entity_type, entity_value, entity.confidence),
            )
            entity_ids.append(str(cursor.fetchone()[0]))
    return entity_ids
