"""
CEOPRO AI - Dashboard Recent Competitor Activity (presentation layer, not
a new model, no new tables)

The mockup's "Recent Competitor Changes"/"Recent Competitor Activity"
feeds ask for real detected events (new product launched, marketing
campaign detected, price change...) - this platform only ever actually
detects ONE of those honestly today: a real price change, from two
consecutive competitor_prices observations on the same mapping. "New
product launched" and "marketing campaign detected" have no underlying
signal anywhere in this codebase (no product-catalog-diff detection, no
social/ad monitoring) - inventing them here would be exactly the kind of
fabricated insight this platform's own SYSTEM_PROMPT explicitly forbids
the chatbot from doing, so this module does not either. A mapping with
fewer than two price observations simply has no change to report yet -
that's a real, honest absence, not a bug.
"""
DEFAULT_LIMIT = 10

# Market Activity (High/Medium/Low) - the mockup's own per-competitor
# "activity level" badge. There is no marketing/social-activity signal
# anywhere in this platform (see this module's own docstring above), so
# this is a real, honestly-scoped proxy: how many actual price CHANGES
# (not just observations) were detected for this competitor in the
# trailing window - a competitor whose price keeps moving is one we're
# genuinely seeing more activity from, which is the one real signal this
# platform has for "how active is this rival right now". Thresholds are a
# deliberate, documented judgment call, not a discovered constant - a
# tenant that wants a stricter/looser bar can ask for these to become
# parameters later.
MARKET_ACTIVITY_WINDOW_DAYS = 30
MARKET_ACTIVITY_HIGH_THRESHOLD = 3   # >= this many real price changes in the window
MARKET_ACTIVITY_MEDIUM_THRESHOLD = 1  # >= this many, below the High bar
LEVEL_HIGH = "High"
LEVEL_MEDIUM = "Medium"
LEVEL_LOW = "Low"


def get_recent_competitor_price_changes(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH ranked AS (
                SELECT cpr.mapping_id, cpr.scraped_price, cpr.currency, cpr.observed_at,
                       ROW_NUMBER() OVER (PARTITION BY cpr.mapping_id ORDER BY cpr.observed_at DESC) AS rn
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = %(tenant_id)s
            )
            SELECT gc.competitor_name,
                   COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                   latest.scraped_price, prior.scraped_price, latest.currency, latest.observed_at
            FROM ranked latest
            JOIN ranked prior ON prior.mapping_id = latest.mapping_id AND prior.rn = 2
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = %(tenant_id)s AND cpm.mapping_id = latest.mapping_id
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            WHERE latest.rn = 1 AND p.deleted_at IS NULL
            ORDER BY latest.observed_at DESC
            LIMIT %(limit)s;
            """,
            {"tenant_id": tenant_id, "limit": limit},
        )
        rows = cursor.fetchall()

    changes = []
    for competitor_name, product_name, latest_price, prior_price, currency, observed_at in rows:
        latest_price = float(latest_price)
        prior_price = float(prior_price)
        change_pct = round((latest_price - prior_price) / prior_price * 100, 1) if prior_price else None
        direction = "unchanged" if not change_pct else ("increase" if change_pct > 0 else "decrease")
        changes.append({
            "competitor_name": competitor_name,
            "product_name": product_name,
            "latest_price": latest_price,
            "prior_price": prior_price,
            "currency": currency,
            "price_change_pct": change_pct,
            "direction": direction,
            "observed_at": observed_at.isoformat(),
        })
    return changes


def _level_for_change_count(change_count: int) -> str:
    if change_count >= MARKET_ACTIVITY_HIGH_THRESHOLD:
        return LEVEL_HIGH
    if change_count >= MARKET_ACTIVITY_MEDIUM_THRESHOLD:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def get_market_activity_levels(conn, tenant_id: str, window_days: int = MARKET_ACTIVITY_WINDOW_DAYS) -> dict:
    """
    {global_competitor_id (str): "High"|"Medium"|"Low"} for every
    competitor with at least one price observation in the trailing
    window - see this module's own MARKET_ACTIVITY_* constants for
    exactly what "activity" means here and why. A competitor with zero
    observations in the window simply isn't in the returned dict; callers
    (dashboard/competitors.py) default a missing key to Low rather than
    treating it as unknown - no detected change is itself the real,
    honest signal for "quiet right now", not a missing-data case.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH ranked AS (
                SELECT cpm.global_competitor_id, cpr.scraped_price,
                       LAG(cpr.scraped_price) OVER (PARTITION BY cpr.mapping_id ORDER BY cpr.observed_at) AS prior_price
                FROM competitor_prices cpr
                JOIN competitor_product_mappings cpm ON cpm.tenant_id = cpr.tenant_id AND cpm.mapping_id = cpr.mapping_id
                WHERE cpr.tenant_id = %(tenant_id)s
                  AND cpr.observed_at >= NOW() - (%(window_days)s || ' days')::interval
            )
            SELECT global_competitor_id,
                   COUNT(*) FILTER (WHERE prior_price IS NOT NULL AND prior_price != scraped_price)
            FROM ranked
            GROUP BY global_competitor_id;
            """,
            {"tenant_id": tenant_id, "window_days": window_days},
        )
        rows = cursor.fetchall()

    return {str(competitor_id): _level_for_change_count(int(change_count)) for competitor_id, change_count in rows}
