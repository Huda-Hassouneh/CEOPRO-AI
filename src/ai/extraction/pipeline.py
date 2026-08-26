"""
CEOPRO AI - Extraction Pipeline Orchestration (spec S15).
Loads 'Pending' news_record/social_mention rows -> runs regex + catalog-match
extraction against each -> persists results to extracted_entity -> marks the
source row 'Processed' or 'Failed' (spec S12: never silently discard invalid
data), mirroring rag/pipeline.py's ingest_pending_documents() convention.

Deliberately writes no evidence_records: bulk entity extraction is an
annotation step over raw text, not itself a user-facing conclusion - same
reasoning sentiment/pipeline.py's classify_and_store_reviews() already
documents for bulk sentiment labeling.
"""

import logging

from src.ai.extraction import data_access, evidence
from src.ai.extraction.extractor import extract_entities

logger = logging.getLogger("CEOPRO_AI_EXTRACTION_PIPELINE")


def _load_catalogs(conn, tenant_id: str):
    return data_access.load_known_product_names(conn, tenant_id), data_access.load_known_competitor_names(
        conn, tenant_id
    )


def extract_and_store_news_records(conn, tenant_id: str, limit: int = 100) -> int:
    known_products, known_competitors = _load_catalogs(conn, tenant_id)
    pending = data_access.load_pending_news_records(conn, tenant_id, limit)
    processed_count = 0

    for record in pending:
        try:
            entities = extract_entities(record["body_text"], known_products, known_competitors)
            evidence.insert_extracted_entities(conn, tenant_id, "news_record", record["news_id"], entities)
            data_access.mark_news_record_status(conn, record["news_id"], "Processed")
            processed_count += 1
        except Exception as err:
            logger.error(f"Failed to extract entities for news_record={record['news_id']}: {err}")
            data_access.mark_news_record_status(conn, record["news_id"], "Failed")

    conn.commit()
    logger.info(f"News extraction complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count


def extract_and_store_social_mentions(conn, tenant_id: str, limit: int = 100) -> int:
    known_products, known_competitors = _load_catalogs(conn, tenant_id)
    pending = data_access.load_pending_social_mentions(conn, tenant_id, limit)
    processed_count = 0

    for record in pending:
        try:
            entities = extract_entities(record["mention_text"], known_products, known_competitors)
            evidence.insert_extracted_entities(conn, tenant_id, "social_mention", record["mention_id"], entities)
            data_access.mark_social_mention_status(conn, record["mention_id"], "Processed")
            processed_count += 1
        except Exception as err:
            logger.error(f"Failed to extract entities for social_mention={record['mention_id']}: {err}")
            data_access.mark_social_mention_status(conn, record["mention_id"], "Failed")

    conn.commit()
    logger.info(f"Social mention extraction complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count
