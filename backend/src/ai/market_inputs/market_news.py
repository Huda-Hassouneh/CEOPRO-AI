"""Industry and competitor news for a company (market_discovery/news.py),
stored once per article with when it was read."""
from typing import List, Optional


def save(conn, tenant_id: str, articles: List[dict]) -> int:
    """Adds new articles (an article already stored is left as it is)."""
    added = 0
    with conn.cursor() as cursor:
        for article in articles:
            competitor_id = None
            if article.get("competitor"):
                cursor.execute(
                    """
                    SELECT tc.global_competitor_id FROM tenant_competitors tc
                    JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
                    WHERE tc.tenant_id = %s AND LOWER(gc.competitor_name) = LOWER(%s) LIMIT 1;
                    """,
                    (tenant_id, article["competitor"]),
                )
                row = cursor.fetchone()
                competitor_id = row[0] if row else None
            cursor.execute(
                """
                INSERT INTO market_news (tenant_id, url, title, source_domain, language, published_at, topic, global_competitor_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, url) DO NOTHING;
                """,
                (tenant_id, article["url"], article["title"], article.get("source_domain"), article.get("language"),
                 article.get("published_at"), article["topic"], competitor_id),
            )
            added += cursor.rowcount
    return added


def latest(conn, tenant_id: str, limit: int = 30, competitor_id: Optional[str] = None) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT n.url, n.title, n.source_domain, n.language, n.published_at, n.topic, n.global_competitor_id,
                   gc.competitor_name, n.retrieved_at
            FROM market_news n LEFT JOIN global_competitors gc ON gc.global_competitor_id = n.global_competitor_id
            WHERE n.tenant_id = %s {"AND n.global_competitor_id = %s" if competitor_id else ""}
            ORDER BY n.published_at DESC NULLS LAST, n.retrieved_at DESC LIMIT %s;
            """,
            (tenant_id, competitor_id, limit) if competitor_id else (tenant_id, limit),
        )
        rows = cursor.fetchall()
    return [{"url": url, "title": title, "source_domain": domain, "language": language,
             "published_at": published.isoformat() if published else None, "topic": topic,
             "competitor_id": str(cid) if cid else None, "competitor_name": name, "retrieved_at": retrieved.isoformat()}
            for url, title, domain, language, published, topic, cid, name, retrieved in rows]
