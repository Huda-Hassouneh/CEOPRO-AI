"""
CEOPRO AI - Extraction Data Access.
Reads known product/competitor names to match against, and pending
news_record/social_mention rows to extract from - all pre-existing tables
this track only reads. Status updates (extraction_status) are the only write
this module makes to those two tables; entity results themselves go to
extracted_entity via evidence.py, this track's own table.
"""

from typing import List


def load_known_product_names(conn, tenant_id: str) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,)
        )
        return [row[0] for row in cursor.fetchall()]


def load_known_competitor_names(conn, tenant_id: str) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT competitor_name FROM competitors WHERE tenant_id = %s AND is_active = TRUE;", (tenant_id,)
        )
        return [row[0] for row in cursor.fetchall()]


def load_pending_news_records(conn, tenant_id: str, limit: int = 100) -> List[dict]:
    query = """
        SELECT news_id, body_text
        FROM news_record
        WHERE tenant_id = %s
          AND extraction_status = 'Pending'
          AND body_text IS NOT NULL
          AND length(trim(body_text)) > 0
        ORDER BY created_at
        LIMIT %s;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, limit))
        rows = cursor.fetchall()
    return [{"news_id": str(row[0]), "body_text": row[1]} for row in rows]


def load_pending_social_mentions(conn, tenant_id: str, limit: int = 100) -> List[dict]:
    query = """
        SELECT mention_id, mention_text
        FROM social_mention
        WHERE tenant_id = %s
          AND extraction_status = 'Pending'
          AND mention_text IS NOT NULL
          AND length(trim(mention_text)) > 0
        ORDER BY created_at
        LIMIT %s;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, limit))
        rows = cursor.fetchall()
    return [{"mention_id": str(row[0]), "mention_text": row[1]} for row in rows]


def mark_news_record_status(conn, news_id: str, status: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute("UPDATE news_record SET extraction_status = %s WHERE news_id = %s;", (status, news_id))


def mark_social_mention_status(conn, mention_id: str, status: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE social_mention SET extraction_status = %s WHERE mention_id = %s;", (status, mention_id)
        )
