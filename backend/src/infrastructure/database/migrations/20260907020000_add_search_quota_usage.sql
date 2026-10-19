-- CEOPRO AI - Daily Google Custom Search quota tracking.
--
-- The real zero-dollar answer to "what happens when 100 free queries/day
-- runs out": pace a bounded, one-time onboarding job across days for
-- free, rather than pay for overage or stand up a second search backend
-- (SearXNG) as the primary volume strategy - see search_quota.py's own
-- docstring for the full reasoning. This table is how "today's budget is
-- gone" gets checked before a real Google call is attempted, so the
-- account never accidentally exceeds the free tier.
--
-- Not tenant-scoped, same reasoning as web_search_cache
-- (20260907010000_add_search_cache_and_competitor_tier.sql): Google's
-- 100/day quota is per API key, i.e. platform-wide, not per tenant - a
-- tenant-scoped counter would undercount the real shared constraint.
CREATE TABLE IF NOT EXISTS search_quota_usage (
    usage_date DATE PRIMARY KEY,
    query_count INT NOT NULL DEFAULT 0
);
