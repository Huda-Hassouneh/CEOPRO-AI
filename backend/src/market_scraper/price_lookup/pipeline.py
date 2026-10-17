"""
Finds a market reference price for tenant products that have none.

A product qualifies when it has no competitor price, no usable reference price
yet, and has not been looked up within PRICE_LOOKUP_RETRY_DAYS (so a product
nobody sells is not searched - and paid for - every run). For each, providers
run cheapest first (providers.configured_order()) and stop at the first one
that yields an acceptable quote; PRICE_LOOKUP_ALL_PROVIDERS=true keeps going to
collect more evidence. A quote is kept only if its title matches our product
(matching.py). One that is far from our own price is stored but flagged
implausible and does not count as coverage.

Bounded: at most PRICE_LOOKUP_MAX_PER_RUN products per run. Every outcome is
recorded in market_price_lookups, including 'nothing found' and 'not
configured', so a gap always says what was tried.
"""
import json
import logging
import os
from typing import Callable, Dict, List, Optional

from src.ai.pricing import currency as fx
from src.market_scraper.price_lookup import matching, providers
from src.market_scraper.price_lookup.models import PriceQuote, ProductContext, ProviderError, ProviderUnavailable

logger = logging.getLogger("KEEL_PRICE_LOOKUP")

OUTCOME_FOUND = "FOUND"
OUTCOME_NOTHING = "NOTHING_FOUND"
OUTCOME_NOT_CONFIGURED = "NOT_CONFIGURED"
OUTCOME_ERROR = "PROVIDER_ERROR"


def _retry_days() -> int:
    return int(os.getenv("PRICE_LOOKUP_RETRY_DAYS", "7"))


def products_needing_a_price(conn, tenant_id: str, limit: int, force: bool = False) -> List[ProductContext]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT country_code, primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        company = cursor.fetchone() or (None, None)
        cursor.execute(
            """
            SELECT p.product_id, COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text), p.current_price
            FROM products p
            LEFT JOIN market_price_lookups l ON l.tenant_id = p.tenant_id AND l.product_id = p.product_id
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM competitor_product_mappings m
                  JOIN tenant_competitors tc ON tc.tenant_id = m.tenant_id AND tc.global_competitor_id = m.global_competitor_id AND tc.is_tracked = TRUE
                  JOIN competitor_prices cpr ON cpr.tenant_id = m.tenant_id AND cpr.mapping_id = m.mapping_id
                  WHERE m.tenant_id = p.tenant_id AND m.product_id = p.product_id AND m.is_active = TRUE)
              AND NOT EXISTS (
                  SELECT 1 FROM market_price_observations o
                  WHERE o.tenant_id = p.tenant_id AND o.product_id = p.product_id AND o.plausible IS NOT FALSE)
              AND (%s OR l.last_attempt_at IS NULL OR l.last_attempt_at < NOW() - make_interval(days => %s))
            ORDER BY l.last_attempt_at NULLS FIRST, p.created_at
            LIMIT %s;
            """,
            (tenant_id, force, _retry_days(), limit),
        )
        rows = cursor.fetchall()
    return [
        ProductContext(str(pid), name, company[0], company[1], float(price) if price is not None else None)
        for pid, name, price in rows if name
    ]


def _plausible(conn, quote: PriceQuote, ctx: ProductContext) -> Optional[bool]:
    reference = ctx.your_price
    if reference is None or not ctx.currency:
        return None
    price = quote.price
    if quote.currency != ctx.currency:
        converted = fx.convert(conn, quote.price, quote.currency, ctx.currency)
        if converted is None:
            return None  # no verified rate: cannot judge, and we do not guess
        price = converted.converted_amount
    return matching.plausible_price(price, reference)


def _store(conn, tenant_id: str, ctx: ProductContext, quote: PriceQuote, score: float, plausible: Optional[bool]) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO market_price_observations
                (tenant_id, product_id, provider, seller_name, product_title, source_url, price, currency,
                 rating, review_count, match_score, plausible, dedupe_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, product_id, dedupe_key) DO UPDATE SET observed_at = NOW()
            RETURNING (xmax = 0);
            """,
            (
                tenant_id, ctx.product_id, quote.provider, quote.seller, quote.title[:300], quote.url, quote.price, quote.currency,
                quote.rating, quote.review_count, score, plausible,
                matching.dedupe_key(quote.provider, quote.seller, quote.url, quote.price, quote.currency),
            ),
        )
        return bool(cursor.fetchone()[0])


def _record_lookup(conn, tenant_id: str, ctx: ProductContext, outcome: str, tried: List[str], found: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO market_price_lookups (tenant_id, product_id, outcome, providers_tried, quotes_found)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (tenant_id, product_id) DO UPDATE SET
                outcome = EXCLUDED.outcome, providers_tried = EXCLUDED.providers_tried, quotes_found = EXCLUDED.quotes_found,
                attempts = market_price_lookups.attempts + 1, last_attempt_at = NOW();
            """,
            (tenant_id, ctx.product_id, outcome, json.dumps(tried), found),
        )


def lookup_product(conn, tenant_id: str, ctx: ProductContext, instances: Dict[str, object], order: List[str], all_providers: bool = False) -> dict:
    tried, kept, errors, unavailable = [], 0, 0, 0
    for name in order:
        provider = instances[name]
        if not provider.available():
            unavailable += 1
            continue
        tried.append(name)
        try:
            quotes = provider.search(ctx)
        except ProviderUnavailable:
            unavailable += 1
            tried.pop()
            continue
        except ProviderError as exc:
            errors += 1
            logger.warning("price lookup via %s failed for product %s: %s", name, ctx.product_id, exc)
            continue
        for quote in quotes:
            score = matching.match_score(ctx.name, quote.title)
            if not matching.is_match(score):
                continue
            plausible = _plausible(conn, quote, ctx)
            _store(conn, tenant_id, ctx, quote, score, plausible)
            if plausible is not False:
                kept += 1
        if kept and not all_providers:
            break
    if kept:
        outcome = OUTCOME_FOUND
    elif not tried:
        outcome = OUTCOME_NOT_CONFIGURED
    elif errors and errors == len(tried):
        outcome = OUTCOME_ERROR
    else:
        outcome = OUTCOME_NOTHING
    _record_lookup(conn, tenant_id, ctx, outcome, tried, kept)
    conn.commit()
    return {"product_id": ctx.product_id, "outcome": outcome, "providers_tried": tried, "quotes_kept": kept}


def lookup_missing_prices(
    conn, tenant_id: str, limit: Optional[int] = None, force: bool = False, provider_instances: Optional[Dict[str, object]] = None,
) -> dict:
    limit = limit if limit is not None else int(os.getenv("PRICE_LOOKUP_MAX_PER_RUN", "20"))
    order = providers.configured_order()
    instances = provider_instances or {name: providers.PROVIDERS[name]() for name in order}
    all_providers = os.getenv("PRICE_LOOKUP_ALL_PROVIDERS", "false").strip().lower() in ("1", "true", "yes")
    candidates = products_needing_a_price(conn, tenant_id, limit, force)
    outcomes: Dict[str, int] = {}
    for ctx in candidates:
        try:
            result = lookup_product(conn, tenant_id, ctx, instances, order, all_providers)
        except Exception:  # noqa: BLE001 - one product must not stop the rest
            conn.rollback()
            logger.exception("price lookup failed for product %s", ctx.product_id)
            continue
        outcomes[result["outcome"]] = outcomes.get(result["outcome"], 0) + 1
    return {"products_attempted": sum(outcomes.values()), "candidates": len(candidates), "outcomes": outcomes}
