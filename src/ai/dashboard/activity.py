"""
CEOPRO AI - Dashboard Recent Activity Feed (presentation layer, not a new
model, no new tables).

The mockup's "Recent Activity" feed - real, from timestamps every one of
these four event types already has in the existing schema:
- File uploaded: ingestion_jobs (joined to data_sources for a real filename).
- New competitor tracked: tenant_competitors.added_at.
- Forecast generated: demand_forecasts.created_at.
- Product added: products.created_at.

No new table, no audit log: this is a UNION of four already-timestamped
event sources the platform already writes to during its normal work,
re-labeled for the feed. Only ingestion_jobs carries a real status
(QUEUED/PROCESSING/COMPLETED/FAILED) - the other three either happened or
they didn't, so their "status" is left null rather than fabricating
"Completed" for an event type that has no such concept.
"""
DEFAULT_LIMIT = 10


def get_recent_activity(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            (
                SELECT 'FILE_UPLOADED' AS activity_type, 'File Uploaded' AS title,
                       ds.source_name AS detail, ij.job_status AS status, ij.created_at AS occurred_at
                FROM ingestion_jobs ij
                JOIN data_sources ds ON ds.tenant_id = ij.tenant_id AND ds.source_id = ij.source_id
                WHERE ij.tenant_id = %(tenant_id)s
            )
            UNION ALL
            (
                SELECT 'COMPETITOR_TRACKED', 'New Competitor Tracked',
                       gc.competitor_name, NULL, tc.added_at
                FROM tenant_competitors tc
                JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
                WHERE tc.tenant_id = %(tenant_id)s AND tc.is_tracked = TRUE
            )
            UNION ALL
            (
                SELECT 'FORECAST_GENERATED', 'Forecast Generated',
                       COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text), NULL, df.created_at
                FROM demand_forecasts df
                JOIN products p ON p.tenant_id = df.tenant_id AND p.product_id = df.product_id
                WHERE df.tenant_id = %(tenant_id)s
            )
            UNION ALL
            (
                SELECT 'PRODUCT_ADDED', 'Product Added',
                       COALESCE(product_name->>'en', product_name->>'ar', product_name::text), NULL, created_at
                FROM products
                WHERE tenant_id = %(tenant_id)s AND deleted_at IS NULL
            )
            ORDER BY occurred_at DESC
            LIMIT %(limit)s;
            """,
            {"tenant_id": tenant_id, "limit": limit},
        )
        rows = cursor.fetchall()

    return [
        {
            "activity_type": activity_type,
            "title": title,
            "detail": detail,
            "status": status,
            "occurred_at": occurred_at.isoformat(),
        }
        for activity_type, title, detail, status, occurred_at in rows
    ]
