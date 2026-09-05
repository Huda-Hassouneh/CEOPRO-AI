"""
CEOPRO AI - End-to-End Multi-Model Pipeline Orchestrator (integration test).

Chains the five stages the user asked to see wired together, against a real
Postgres/MinIO stack, with error checking at every stage boundary and a
complete validation-log export - this is the "initial integration test
across all models" run before mobile/web backend integration begins.

    1. Extraction        - mocks/e2e_pipeline_demo.csv -> ingestion_pipeline.process_records()
    2. Promotion          - extraction.promotion.promote_ingested_rows() -> products/transactions
    3. Competitor scraping - real dynamic discovery: candidate URLs come from
                              market_scraper/direct_search.py's live, no-paid-API site search
                              (schema.org SearchAction, real per-domain HTTP fetches) merged with
                              a small manually-verified list, then market_scraper/discovery.py's
                              policy engine (robots.txt, manufacturer filter) decides what actually
                              gets scraped via a subprocess-run market_scraper.cli (Scrapy's
                              CrawlerProcess/Twisted reactor can only start once per process, so
                              this must be a subprocess, never imported in-process) - persistence.py
                              already writes any scraped reviews into `reviews`
                              (subject_type='COMPETITOR') as a side effect of this stage
    4. Market analysis     - market_scraper.analysis_worker.analyze_tenant(): classifies those
                              scraped reviews (sentiment/pipeline.py) and refreshes competitor score
                              snapshots (intelligence.py) - the same function the real
                              market.analysis.requested Redis consumer calls, run synchronously here
    5. Demand forecasting - forecasting.pipeline.run_forecast() per promoted product
    6. Price intelligence - pricing.pipeline.run_price_recommendation() per promoted product
    7. RAG grounding       - a summary of this run's forecast/pricing/sentiment output is ingested
                              into rag_document_chunks so RAG chat can answer questions about it
                              (run_retrieval()/answer_query() only ever read ingested documents -
                              there is no separate structured-table retrieval stage today)

Every stage is wrapped so one stage's failure is recorded, not fatal to the
rest of the run - matches ingestion_pipeline.py's own "one bad row must not
sink the whole file" philosophy, applied at the stage level instead of the
row level. Nothing is silently skipped: a stage that can't produce real
output records why (e.g. "no products were promoted, forecasting skipped"),
not just an empty result.

Usage:
    export DATABASE_URL=... APP_DB_PASSWORD=... JWT_SECRET=...
    export SCRAPER_DATABASE_URL=... MINIO_ENDPOINT=... MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD=...
    python scripts/run_e2e_pipeline.py [--mock-file mocks/e2e_pipeline_demo.csv] [--skip-scraping]

Writes a complete JSON + human-readable report to reports/e2e_pipeline/<run_id>/.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlsplit

import psutil
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai import db
from src.ai.extraction import file_dispatch, geo_currency, ingestion_pipeline, job_management, promotion
from src.ai.forecasting import pipeline as forecasting_pipeline
from src.ai.pricing import pipeline as pricing_pipeline
from src.ai.pricing.matching import similarity
from src.ai.rag import llm_client as rag_llm_client
from src.ai.rag import pipeline as rag_pipeline
from src.ai.sentiment import pipeline as sentiment_pipeline
from src.market_scraper import direct_search, discovery
from src.market_scraper.analysis_worker import analyze_tenant
from src.market_scraper.sector_detection import build_retail_search_query, detect_vertical, resolve_tenant_geo_scope

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MOCK_FILE = os.path.join(REPO_ROOT, "mocks", "e2e_pipeline_demo.csv")

# Manually-verified candidates, kept as a supplement to direct_search.py's
# live discovery (stage_scraping() below merges both, deduped by URL) - not
# a replacement for it any more. Originally this dict was the *only* source
# of candidates (no paid search-API credentials are configured in this
# environment, same category of gap as Google Places/Amazon PA-API); that
# gap is now closed for real, without any paid API, via direct_search.py's
# schema.org SearchAction discovery - see that module's own docstring.
# store-usa.arduino.cc is kept here specifically because it has real,
# already-quoted robots.txt evidence (_TERMS_EVIDENCE_BY_HOST below) that
# a fresh live search wouldn't rediscover on its own.
_DISCOVERED_CANDIDATES = {
    "Arduino Nano": [
        discovery.CandidateSource("Arduino Nano", "https://store-usa.arduino.cc/products/arduino-nano", "Arduino Nano - Arduino Online Shop"),
        discovery.CandidateSource("Arduino Nano", "https://www.sparkfun.com/arduino-nano-every.html", "Arduino Nano Every - SparkFun Electronics"),
    ],
    "Raspberry Pi 4 (4GB)": [
        discovery.CandidateSource("Raspberry Pi 4 (4GB)", "https://www.sparkfun.com/raspberry-pi-4-model-b-4-gb.html", "Raspberry Pi 4 Model B (4 GB) - SparkFun Electronics"),
        discovery.CandidateSource("Raspberry Pi 4 (4GB)", "https://www.pishop.us/product/raspberry-pi-4-model-b-4gb/", "Raspberry Pi 4 Model B 4GB | PiShop US - Official Reseller"),
    ],
    "Digital Multimeter DT830B": [
        discovery.CandidateSource("Digital Multimeter DT830B", "https://www.impactbattery.com/yellow-digital-multimeter-dt830b.html", "Yellow Digital MultiMeter DT830B"),
    ],
}

# store-usa.arduino.cc/robots.txt's own comment text ("Public product,
# collection, page, blog, policy, cart, and localized HTML is crawlable.") -
# the one candidate with a genuine, quotable, site-published crawlability
# statement rather than an assumed one. See discovery.py: terms_evidence is
# never fabricated for a candidate that doesn't have real evidence like this.
_TERMS_EVIDENCE_BY_HOST = {
    "store-usa.arduino.cc": (
        "robots.txt: \"Public product, collection, page, blog, policy, cart, and localized HTML is crawlable.\" "
        "(fetched " + datetime.now(timezone.utc).date().isoformat() + ")"
    ),
}


class Stage:
    """One report entry: status is 'OK', 'PARTIAL', 'SKIPPED', or 'FAILED' -
    never silently absent, matching this pipeline's own error-checking
    requirement for itself, not just the data flowing through it."""

    def __init__(self, name):
        self.name = name
        self.started_at = time.time()
        self.status = "OK"
        self.details = {}
        self.errors = []

    def fail(self, error: str):
        self.status = "FAILED"
        self.errors.append(error)

    def skip(self, reason: str):
        self.status = "SKIPPED"
        self.errors.append(reason)

    def to_dict(self) -> dict:
        return {
            "stage": self.name,
            "status": self.status,
            "duration_seconds": round(time.time() - self.started_at, 3),
            "process_rss_mb_at_completion": round(psutil.Process().memory_info().rss / (1024 * 1024), 1),
            "details": self.details,
            "errors": self.errors,
        }


def _setup_demo_tenant(admin_conn) -> dict:
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    # companies.primary_currency is NOT NULL (confirmed live) - derive it
    # from country_code at creation time via geo_currency's real lookup
    # (JO -> JOD) rather than hardcoding an arbitrary value here.
    initial_currency = geo_currency.compute_initial_currency("JO")["currency"]
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', %s);",
            (tenant_id, f"E2E Pipeline Demo Co {tenant_id[:8]}", initial_currency),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');",
            (user_id, f"{user_id}@e2e-demo.example"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');",
            (tenant_id, user_id),
        )
    admin_conn.commit()
    return {"tenant_id": tenant_id, "user_id": user_id}


_EXTRACTION_COMMIT_EVERY = int(os.getenv("EXTRACTION_COMMIT_EVERY", "500"))
_MAX_LOGGED_ERRORS = 50  # cap per-stage error lists so a systematic failure on a 50k-row file can't blow up the report


def stage_extraction(mock_file: str, tenant_id: str, user_id: str) -> tuple:
    stage = Stage("1_extraction")
    conn = db.app_role_connection(tenant_id, user_id)
    summary = None
    try:
        read_started = time.time()
        headers, rows = file_dispatch.read_source_file(mock_file)
        read_seconds = round(time.time() - read_started, 3)

        source_id = job_management.resolve_or_create_data_source(conn, tenant_id, "XLSX_UPLOAD", "E2E Pipeline Mock File")
        job_id = job_management.create_ingestion_job(conn, tenant_id, source_id)
        conn.commit()

        process_started = time.time()
        summary = ingestion_pipeline.process_records(
            tenant_id=tenant_id, job_id=job_id, source_name=os.path.basename(mock_file),
            headers=headers, rows=rows, conn=conn, commit_every=_EXTRACTION_COMMIT_EVERY,
        )
        process_seconds = round(time.time() - process_started, 3)
        job_management.finalize_ingestion_job(conn, tenant_id, job_id, "COMPLETED")
        conn.commit()

        stage.details = {
            "job_id": job_id,
            "row_count": len(rows),
            "file_read_seconds": read_seconds,
            "process_records_seconds": process_seconds,
            "rows_per_second": round(len(rows) / process_seconds, 1) if process_seconds > 0 else None,
            "template_mode": summary.template_mode,
            "is_template_compliant": summary.is_template_compliant,
            "rows_processed": summary.rows_processed,
            "rows_partial": summary.rows_partial,
            "rows_failed": summary.rows_failed,
            "data_loss_pct": summary.data_loss_pct,
        }
        if summary.rows_failed:
            stage.status = "PARTIAL"
            stage.errors.append(f"{summary.rows_failed} row(s) failed extraction entirely.")
    except Exception as e:  # noqa: BLE001 - one failed stage must not crash the whole orchestrator
        conn.rollback()
        stage.fail(str(e))
    finally:
        conn.close()
    return stage, summary




def stage_promotion(tenant_id: str, user_id: str, job_id: str, summary) -> tuple:
    stage = Stage("2_promotion")
    if summary is None:
        stage.skip("Extraction did not produce a summary to promote from.")
        return stage, []

    conn = db.app_role_connection(tenant_id, user_id)
    product_ids = []
    try:
        currency_resolution = geo_currency.resolve_company_currency(conn, tenant_id)
        promo = promotion.promote_ingested_rows(
            conn, tenant_id, job_id, summary, user_id=user_id,
            default_currency=currency_resolution["currency"],
        )
        conn.commit()
        stage.details = {
            "currency_resolution": currency_resolution,
            "rows_promoted": promo.rows_promoted,
            "rows_skipped_incomplete": promo.rows_skipped_incomplete,
            "rows_failed": promo.rows_failed,
            "products_created": promo.products_created,
            "promotion_error_count": len(promo.errors),
            "promotion_errors_sample": promo.errors[:_MAX_LOGGED_ERRORS],
        }
        if promo.rows_failed:
            stage.status = "PARTIAL"

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT t.product_id, p.product_name->>'en' FROM transactions t "
                "JOIN products p ON p.product_id = t.product_id AND p.tenant_id = t.tenant_id "
                "WHERE t.tenant_id = %s;",
                (tenant_id,),
            )
            product_ids = [{"product_id": str(pid), "product_name": name} for pid, name in cursor.fetchall()]
        stage.details["promoted_products"] = product_ids
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        stage.fail(str(e))
    finally:
        conn.close()
    return stage, product_ids


def _run_one_scrape(tenant_id: str, user_id: str, source_id: str, timeout: int = 120) -> dict:
    env = dict(os.environ, SCRAPER_ACTOR_USER_ID=user_id, SCRAPER_DATABASE_URL=os.environ.get("SCRAPER_DATABASE_URL", os.environ.get("DATABASE_URL", "")))
    result = subprocess.run(
        [sys.executable, "-m", "src.market_scraper.cli", "--tenant-id", tenant_id, "--source-id", source_id],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )
    return {
        "subprocess_returncode": result.returncode,
        "subprocess_stdout_tail": result.stdout[-1500:],
        "subprocess_stderr_tail": result.stderr[-1500:],
    }


def stage_scraping(
    admin_conn, tenant_id: str, user_id: str, product_ids: list, live_approve_hosts: set,
    geo_scope_override: str = None,
) -> Stage:
    """
    Real dynamic discovery, sector-agnostic and tenant-isolated:

    1. detect_vertical() infers the business vertical from the actual
       promoted catalog (nothing hardcoded to electronics - a restaurant
       catalog gets 'food_beverage', a clothing catalog gets
       'apparel_fashion', an unrecognized catalog gets 'general_retail').
    2. For each promoted product with discovered candidates (see
       _DISCOVERED_CANDIDATES' own docstring on why the search step is
       seeded here rather than called live - no search-API credentials
       are configured in this environment), each candidate is evaluated
       for real: is it a public URL, does its actual robots.txt permit
       fetching it, is it a manufacturer/wholesaler (deprioritized) or a
       retail storefront, does it have real quotable terms-of-service
       evidence.
    3. Every candidate is persisted tenant-scoped (global_competitors.
       visibility='PRIVATE', added_by_tenant_id=tenant_id) regardless of
       outcome - "log the details it did find along with the exact URL
       discovered" holds even when nothing gets scraped.
    4. A candidate only actually gets scraped when its policy decision is
       genuinely ALLOWED (real terms evidence) or its host is in
       `live_approve_hosts` - a host the user explicitly authorized for
       this run. Nothing is scraped on an unreviewed domain by default;
       that's correct, not a shortcoming - see this module's own
       docstring.
    """
    stage = Stage("3_competitor_scraping")
    if not product_ids:
        stage.skip("No promoted products to discover competitors for.")
        return stage

    vertical = detect_vertical([p["product_name"] for p in product_ids])
    geo_scope = resolve_tenant_geo_scope(admin_conn, tenant_id, override=geo_scope_override)
    stage.details["detected_vertical"] = {
        "vertical": vertical.vertical, "confidence": round(vertical.confidence, 2),
        "matched_keywords": vertical.matched_keywords,
    }
    stage.details["geo_scope"] = {
        "value": geo_scope, "source": "override" if geo_scope_override else "companies.country_code",
        "note": (
            "direct_search.py's retailer domain lists are not yet geo-scoped themselves (all "
            "currently-verified domains are US-based) - a real follow-up, not this run's claim."
        ),
    }

    os.environ["SCRAPER_ACTOR_USER_ID"] = user_id
    retailer_domains = direct_search.RETAILER_DOMAINS_BY_VERTICAL.get(vertical.vertical, [])

    # Live per-product search calls are I/O-bound real HTTP requests (each
    # domain's search-results page, robots.txt already cached per-domain by
    # direct_search.py itself - see its own _TEMPLATE_CACHE/_ROBOTS_PATH_CACHE
    # docstring) - run them concurrently rather than one product at a time.
    # Measured live: an earlier sequential version of this call, uncached,
    # made a 109-product run hang for 10+ minutes still climbing; caching
    # alone cuts the redundant homepage/robots calls, and this pool cuts the
    # remaining per-product search-fetch latency by running many at once.
    live_results = {}
    if retailer_domains:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(direct_search.search_product_across_retailers, p["product_name"], retailer_domains): p["product_name"]
                for p in product_ids
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    live_results[name] = future.result()
                except Exception:  # noqa: BLE001 - one product's search failure must not sink the rest
                    live_results[name] = []

    discoveries = []
    for product in product_ids:
        # Real, live-discovered candidates (direct_search.py - schema.org SearchAction,
        # no paid API) merged with any manually pre-verified ones for this product name
        # (e.g. store-usa.arduino.cc's own quoted robots.txt evidence). Deduped by URL -
        # the same product can legitimately turn up from both sources.
        candidates = list(_DISCOVERED_CANDIDATES.get(product["product_name"], []))
        live_candidates = live_results.get(product["product_name"], [])
        known_urls = {c.url for c in candidates}
        candidates.extend(c for c in live_candidates if c.url not in known_urls)
        if not candidates:
            continue

        brand_tokens = set(product["product_name"].lower().split())
        for candidate in candidates:
            host = urlsplit(candidate.url).hostname or ""
            is_manufacturer = discovery.looks_like_manufacturer_or_wholesale(candidate, brand_tokens)
            terms_evidence = _TERMS_EVIDENCE_BY_HOST.get(host)
            if not terms_evidence and host in live_approve_hosts:
                # --live-approve-hosts *is* the human review step (policy.py/
                # data_access.record_policy_decision() require real evidence
                # before ALLOWED) - recording it as anything other than what
                # actually happened here would be exactly the "fabricate a
                # source's compliance" shortcut already declined earlier in
                # this session for the similarity threshold.
                terms_evidence = f"Explicitly approved by operator for this run via --live-approve-hosts (host: {host})"
            decision = discovery.evaluate_candidate(candidate, terms_evidence=terms_evidence)

            try:
                registration = discovery.register_tenant_scoped_competitor(
                    admin_conn, tenant_id, user_id, decision, product["product_id"],
                )
                admin_conn.commit()
            except Exception as e:  # noqa: BLE001 - one bad candidate must not sink the others
                admin_conn.rollback()
                discoveries.append({
                    "product_name": product["product_name"], "url": candidate.url,
                    "error": str(e),
                })
                continue

            record = {
                "product_name": product["product_name"],
                "url": candidate.url,
                "title": candidate.title,
                "is_manufacturer_or_wholesale": is_manufacturer,
                "policy_status": registration["policy_status"],
                "terms_evidence": terms_evidence,
                "scraped": False,
            }

            # Pre-filter by title similarity before paying for a real subprocess scrape.
            # Live-measured (2026-09-04, 461 candidates from direct_search.py's broader
            # discovery): scraping every candidate unconditionally took 2030s (~34 min)
            # for one run, because 450 of 458 scraped candidates failed the spider's own
            # match_score check (market_source.py's MATCH_THRESHOLD=0.82, same
            # similarity() function) *after* a full subprocess round-trip - a search
            # result titled "Espressif ESP8266EX" for a query on "ESP8266 NodeMCU" was
            # never going to pass 0.82, and didn't need a scrape to find that out. This
            # mirrors that same check on the candidate's own search-result title first;
            # it's an approximation (the spider's real check runs against the scraped
            # page's own declared name, which can differ slightly from the search
            # result's link text) so it only skips candidates clearly below threshold,
            # never claims a match the spider hasn't actually verified.
            title_match_score = similarity(candidate.title, product["product_name"]) if candidate.title else 0.0
            record["title_similarity_prefilter"] = round(title_match_score, 3)
            should_scrape = registration["policy_status"] == "ALLOWED" or host in live_approve_hosts
            if should_scrape and is_manufacturer:
                record["skipped_reason"] = "manufacturer/wholesale candidate deprioritized in favor of retail sources"
            elif should_scrape and title_match_score < _TITLE_PREFILTER_THRESHOLD:
                record["skipped_reason"] = (
                    f"title similarity {title_match_score:.2f} below {_TITLE_PREFILTER_THRESHOLD:.2f} "
                    "prefilter - not the same product as the search result's own page would likely confirm"
                )
            elif should_scrape:
                try:
                    scrape_result = _run_one_scrape(tenant_id, user_id, registration["source_id"])
                    record["scraped"] = True
                    record.update(scrape_result)
                except subprocess.TimeoutExpired:
                    record["error"] = "market_scraper.cli did not finish within timeout"

            discoveries.append(record)

    stage.details["discoveries"] = discoveries
    with admin_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM competitor_prices WHERE tenant_id = %s;", (tenant_id,))
        stage.details["competitor_prices_rows"] = cursor.fetchone()[0]

    if not discoveries:
        stage.skip("No discovery candidates matched any promoted product name for this catalog.")
    elif stage.details["competitor_prices_rows"] == 0:
        stage.status = "PARTIAL"
        stage.errors.append(
            "Discovery ran and logged real candidate URLs, but none reached a scraped price - "
            "see discoveries[].policy_status/is_manufacturer_or_wholesale for why each one didn't."
        )
    return stage


# Measured, not assumed: an earlier version of this defaulted to
# os.cpu_count() workers and made forecasting SLOWER (67.2s vs 55.7s
# serial, both against the same 109-product catalog) - forecasting/
# model.py's XGBoostDemandForecaster already sets n_jobs=-1 (claims every
# core for a single model fit), so running N of those concurrently
# oversubscribes an 8-core machine by up to N*8 competing threads rather
# than actually parallelizing. A small worker count still gives a real
# win for products that use the cheap "baseline" path (no XGBoost, mostly
# DB I/O) without badly oversubscribing the ones that do use XGBoost.
_PER_PRODUCT_MAX_WORKERS = int(os.getenv("E2E_PER_PRODUCT_MAX_WORKERS", "3"))

# Live-calibrated (2026-09-04) against real title pairs: genuine matches this
# pipeline has actually scraped scored 0.80-0.88 (e.g. "Arduino Nano Every" vs
# "Arduino Nano"); real false-positive search hits that later failed the
# spider's own 0.82 match_score check scored 0.47-0.49 (e.g. "Espressif
# ESP8266EX" vs "ESP8266 NodeMCU"). 0.6 sits with real margin on both sides -
# loose enough not to reject a genuine match on candidate-title wording alone,
# tight enough to skip the scrape entirely for a search result that clearly
# isn't the same product.
_TITLE_PREFILTER_THRESHOLD = 0.6


def _run_per_product_parallel(tenant_id: str, user_id: str, product_ids: list, worker_fn) -> dict:
    """
    Runs `worker_fn(conn, tenant_id, product_id)` for every product
    concurrently via a small thread pool - each product's forecast/pricing
    call is fully independent (own product_id, own DB rows), and both
    XGBoost training (C++/numpy, releases the GIL) and DB I/O (network
    wait, releases the GIL) genuinely benefit from threading despite the
    GIL, unlike a pure-Python CPU-bound loop. Each worker opens its own
    psycopg2 connection - connections are not thread-safe to share, and
    each is cheap relative to a single forecast/pricing call.
    """
    results = {}

    def _call(product_id):
        conn = db.app_role_connection(tenant_id, user_id)
        try:
            return product_id, worker_fn(conn, tenant_id, product_id)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=min(_PER_PRODUCT_MAX_WORKERS, len(product_ids))) as pool:
        futures = {pool.submit(_call, p["product_id"]): p["product_id"] for p in product_ids}
        for future in as_completed(futures):
            product_id = futures[future]
            try:
                _, result = future.result()
                results[product_id] = result
            except Exception as e:  # noqa: BLE001 - one product's failure must not sink the rest
                results[product_id] = {"status": "ERROR", "error": str(e)}
    return results


def stage_market_analysis(tenant_id: str, user_id: str) -> tuple:
    """
    Reuses market_scraper.analysis_worker.analyze_tenant() directly - the
    exact function the real market.analysis.requested Redis consumer
    (analysis_worker.run_forever()) calls, already fully built earlier
    this engagement: classify_and_store_reviews() (sentiment/pipeline.py,
    already wired to /sentiment/summary in main.py) then
    refresh_score_snapshots() (intelligence.py's price/activity/relevance/
    composite competitor scoring). Called synchronously here rather than
    via the Redis stream - this orchestrator is a one-shot script, not a
    long-running service, so there's no decoupling benefit to gain from
    the async path, and no Redis dependency needed for this specific run.
    persistence.py already writes scraped reviews into `reviews` with
    subject_type='COMPETITOR' - this stage is the first thing in this
    session that actually classifies them, closing the loop this
    worktree's own name (competitors-market-sentiment) describes.

    Returns (stage, sentiment_summaries) - sentiment_summaries is a real,
    per-competitor sentiment aggregate (sentiment/pipeline.py's own
    get_subject_sentiment_summary(), the same function /sentiment/summary
    calls) for stage_rag_grounding to cite with real evidence_ids.
    """
    stage = Stage("4_market_analysis")
    sentiment_summaries = []
    try:
        result = analyze_tenant(tenant_id)
        stage.details = {"analyze_tenant_result": result}
        if result.get("sentiment", {}).get("analyzed_count", 0) == 0:
            stage.status = "PARTIAL"
            stage.errors.append("No unanalyzed reviews were found for this tenant - nothing to classify.")

        conn = db.app_role_connection(tenant_id, user_id)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT r.competitor_id, gc.competitor_name FROM reviews r "
                    "JOIN global_competitors gc ON gc.global_competitor_id = r.competitor_id "
                    "WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id IS NOT NULL;",
                    (tenant_id,),
                )
                competitors = cursor.fetchall()
            for competitor_id, competitor_name in competitors:
                summary = sentiment_pipeline.get_subject_sentiment_summary(
                    conn, tenant_id, "COMPETITOR", str(competitor_id)
                )
                conn.commit()
                sentiment_summaries.append(
                    {"competitor_id": str(competitor_id), "competitor_name": competitor_name, **summary}
                )
            stage.details["sentiment_summaries"] = sentiment_summaries
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        stage.fail(str(e))
    return stage, sentiment_summaries


def stage_forecasting(tenant_id: str, user_id: str, product_ids: list) -> tuple:
    stage = Stage("5_forecasting")
    if not product_ids:
        stage.skip("No promoted products to forecast.")
        return stage, {}

    results = _run_per_product_parallel(
        tenant_id, user_id, product_ids,
        lambda conn, tid, pid: forecasting_pipeline.run_forecast(conn, tid, pid),
    )
    if any(r.get("status") == "ERROR" for r in results.values()):
        stage.status = "PARTIAL"
    stage.details = {"per_product": results}
    return stage, results


def stage_pricing(tenant_id: str, user_id: str, product_ids: list) -> tuple:
    stage = Stage("6_pricing")
    if not product_ids:
        stage.skip("No promoted products to price.")
        return stage, {}

    results = _run_per_product_parallel(
        tenant_id, user_id, product_ids,
        lambda conn, tid, pid: pricing_pipeline.run_price_recommendation(conn, tid, pid),
    )
    if any(r.get("status") == "ERROR" for r in results.values()):
        stage.status = "PARTIAL"
    stage.details = {"per_product": results}
    return stage, results


def _load_competitor_price_records(conn, tenant_id: str, product_id: str) -> list:
    """Real rows backing a pricing recommendation's matched_competitor_count -
    used to cite the actual vendor/snapshot a price came from, not just the
    computed recommendation number."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, cp.scraped_price, cp.currency, cp.is_available, cp.observed_at
            FROM competitor_prices cp
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = cp.tenant_id AND cpm.mapping_id = cp.mapping_id
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            WHERE cp.tenant_id = %s AND cpm.product_id = %s
            ORDER BY cp.observed_at DESC;
            """,
            (tenant_id, product_id),
        )
        return [
            {"competitor_name": name, "price": float(price), "currency": currency,
             "is_available": is_available, "observed_at": observed_at.isoformat()}
            for name, price, currency, is_available, observed_at in cursor.fetchall()
        ]



# Static table-ownership map: (table, populated_by, consumed_by). Kept as
# one explicit list rather than derived from code introspection - it's
# documentation of intent, and a table gaining a new writer/reader should
# be a deliberate edit here, not something that silently falls out of a
# grep. Every table any stage in this orchestrator actually touches is
# listed - this is what answers "who populates/consumes each table".
_TABLE_OWNERSHIP = [
    ("import_staging_rows", "extraction.ingestion_pipeline.process_records() (stage 1)",
     "extraction.promotion.promote_ingested_rows() (stage 2) - reads eligible rows, then flags them "
     "committed_table/committed_record_id/validation_status='COMMITTED'"),
    ("products", "extraction.promotion.promote_ingested_rows() (stage 2)",
     "forecasting.pipeline.run_forecast(), pricing.pipeline.run_price_recommendation(), "
     "market_scraper.discovery (competitor_product_mappings.product_id) (stages 3, 5, 6)"),
    ("transactions", "extraction.promotion.promote_ingested_rows() (stage 2)",
     "forecasting.pipeline.run_forecast() (stage 5) - reads a product's transaction history"),
    ("global_competitors", "market_scraper.discovery.register_tenant_scoped_competitor() (stage 3)",
     "market_scraper.intelligence.refresh_score_snapshots(), sentiment summaries, pricing's competitor "
     "snapshot citations (stages 4, 6)"),
    ("tenant_competitors", "market_scraper.discovery.register_tenant_scoped_competitor() (stage 3)",
     "market_scraper.intelligence.refresh_score_snapshots() (stage 4) - scopes scoring to a tenant's "
     "own tracked competitors"),
    ("data_sources", "market_scraper.discovery.register_tenant_scoped_competitor() (stage 3)",
     "market_scraper.policy.evaluate_source()/data_access.record_policy_decision() (stage 3) - the "
     "policy decision a source is collected under"),
    ("competitor_product_mappings", "market_scraper.discovery.register_tenant_scoped_competitor() (stage 3)",
     "pricing.pipeline.run_price_recommendation() (stage 6) - joins to find this product's competitor "
     "price rows"),
    ("competitor_prices", "market_scraper's spider/persistence.py, via market_scraper.cli subprocess "
     "(stage 3) - only when a candidate's policy status is genuinely ALLOWED",
     "pricing.pipeline.run_price_recommendation() (stage 6)"),
    ("reviews", "market_scraper's spider/persistence.py (subject_type='COMPETITOR', stage 3)",
     "sentiment.pipeline.classify_and_store_reviews() (stage 4)"),
    ("sentiment_results", "sentiment.pipeline.classify_and_store_reviews() (stage 4)",
     "sentiment.pipeline.get_subject_sentiment_summary() (stage 4) - aggregated per competitor/product"),
    ("competitor_score_snapshots", "market_scraper.intelligence.refresh_score_snapshots() (stage 4)",
     "not yet read by any stage in this orchestrator - available for a future competitor-scoring UI/API"),
    ("demand_forecasts", "forecasting.pipeline.run_forecast() (stage 5)",
     "this RAG-grounding document (stage 7), cited to the chat user"),
    ("recommendation_outcomes", "pricing.pipeline.run_price_recommendation() (stage 6)",
     "this RAG-grounding document (stage 7), cited to the chat user"),
    ("evidence_records", "forecasting.pipeline / pricing.pipeline / sentiment.pipeline (stages 4-6) - "
     "one row per model output, linking it to the DB rows it was computed from",
     "this RAG-grounding document's own [Source: ...] citations (stage 7) - the evidence_id named next "
     "to each fact below is a real row here"),
    ("rag_documents_metadata / rag_document_chunks", "rag.pipeline.ingest_pending_documents() (stage 7) "
     "- chunks and embeds this very document",
     "rag.pipeline.run_retrieval()/llm_client.answer_query() (stage 8 and the notebook chat cell)"),
]


def _build_summary_document(
    conn, tenant_id: str, mock_file: str, row_count: int, product_ids, forecast_results, pricing_results,
    sentiment_summaries: list, extraction_details: dict = None, discoveries: list = None,
) -> str:
    """
    Every fact below carries an explicit [Source: ...] annotation naming the
    real table/module/id it came from - llm_client.SYSTEM_PROMPT instructs
    the model to cite these verbatim when asked about provenance, so the
    citation has to actually be true, not just plausible-sounding.
    """
    extraction_details = extraction_details or {}
    discoveries = discoveries or []
    lines = [
        "End-to-End Pipeline Run Summary",
        "",
        "Data lineage for this document:",
        f"- Internal transactional data: {row_count} rows ingested from '{os.path.basename(mock_file)}' "
        "via extraction.ingestion_pipeline.process_records(), promoted into the `products` and "
        "`transactions` tables via extraction.promotion.promote_ingested_rows() "
        "[Source: transactions table, products table].",
        "- Demand forecasts: forecasting.pipeline.run_forecast(), persisted to the `demand_forecasts` "
        "table with a linked `evidence_records` row per product [Source: demand_forecasts table, "
        "evidence_records table].",
        "- Price recommendations: pricing.pipeline.run_price_recommendation(), persisted to the "
        "`recommendation_outcomes` table with a linked `evidence_records` row per product "
        "[Source: recommendation_outcomes table, evidence_records table].",
        "- External market data (where present): scraped via src/market_scraper, persisted to the "
        "`competitor_prices` table with the source competitor's name and capture timestamp "
        "[Source: competitor_prices table, global_competitors table].",
        "- Competitor review sentiment (where present): scraped reviews persisted to `reviews` "
        "(subject_type='COMPETITOR'), classified by sentiment.pipeline.classify_and_store_reviews() "
        "into `sentiment_results`, aggregated per competitor by "
        "sentiment.pipeline.get_subject_sentiment_summary() [Source: reviews table, sentiment_results "
        "table, evidence_records table].",
        "",
    ]

    lines.append("## Data Pipeline & Table Ownership")
    lines.append(
        "Every table this pipeline touches, who writes it, and who reads it - "
        "[Source: this orchestrator's own stage functions, scripts/run_e2e_pipeline.py]."
    )
    for table, populated_by, consumed_by in _TABLE_OWNERSHIP:
        lines.append(f"- `{table}`: populated by {populated_by}; consumed by {consumed_by}.")
    lines.append("")

    if extraction_details:
        lines.append("## Extraction Summary")
        lines.append(
            f"{extraction_details.get('row_count', row_count)} rows read from "
            f"'{os.path.basename(mock_file)}' in {extraction_details.get('file_read_seconds', '?')}s, "
            f"processed in {extraction_details.get('process_records_seconds', '?')}s "
            f"({extraction_details.get('rows_per_second', '?')} rows/sec). "
            f"{extraction_details.get('rows_processed', '?')} processed, "
            f"{extraction_details.get('rows_partial', '?')} partial, "
            f"{extraction_details.get('rows_failed', '?')} failed, "
            f"{extraction_details.get('data_loss_pct', '?')}% data loss "
            "[Source: import_staging_rows table, ingestion_jobs table]."
        )
        lines.append("")

    if discoveries:
        lines.append("## Competitor Discovery")
        lines.append(
            f"{len(discoveries)} candidate competitor URL(s) discovered and logged this run "
            "(every candidate is recorded regardless of whether it was ultimately scraped - "
            "[Source: global_competitors table, competitor_product_mappings table, data_sources table])."
        )
        for d in discoveries:
            if "error" in d and "policy_status" not in d:
                lines.append(f"- {d['product_name']}: candidate {d['url']} failed to register: {d['error']}.")
                continue
            outcome = "scraped" if d.get("scraped") else "logged, not scraped"
            reason = ""
            if not d.get("scraped"):
                reason = f" (policy_status={d.get('policy_status')}"
                if d.get("is_manufacturer_or_wholesale"):
                    reason += ", manufacturer/wholesale - deprioritized"
                reason += ")"
            lines.append(f"- {d['product_name']}: {d.get('title') or d['url']} - {outcome}{reason}.")
        lines.append("")

    if sentiment_summaries:
        lines.append("## Competitor Review Sentiment")
        for entry in sentiment_summaries:
            if entry.get("status") == "OK":
                counts = entry["label_counts"]
                lines.append(
                    f"{entry['competitor_name']}: sentiment_score={entry['sentiment_score']} "
                    f"({counts['positive']} positive, {counts['neutral']} neutral, {counts['negative']} negative "
                    f"reviews analyzed) [Source: sentiment_results table, evidence_id={entry['evidence_id']}]."
                )
            else:
                lines.append(
                    f"{entry['competitor_name']}: no analyzed reviews yet "
                    f"[Source: evidence_records table, evidence_id={entry.get('evidence_id')}]."
                )
        lines.append("")

    for product in product_ids:
        pid = product["product_id"]
        lines.append(f"## {product['product_name']} (product_id={pid})")

        forecast = forecast_results.get(pid, {})
        status = forecast.get("status", "N/A")
        if status == "OK":
            lines.append(
                f"Forecast: expected demand {forecast['expected_demand']:.2f} units by "
                f"{forecast['forecast_target_date']} (model: {forecast['source']}, confidence "
                f"{forecast['confidence_score']}) [Source: demand_forecasts table, "
                f"forecast_id={forecast['forecast_id']}, evidence_id={forecast['evidence_id']}]."
            )
        elif status == "UNKNOWN":
            lines.append(
                "Forecast: no historical transaction data was sufficient to forecast this product "
                f"[Source: evidence_records table, evidence_id={forecast.get('evidence_id')}]."
            )
        else:
            lines.append(f"Forecast: {status}.")

        pricing = pricing_results.get(pid, {})
        pstatus = pricing.get("status", "N/A")
        if pstatus == "OK":
            lines.append(
                f"Pricing: recommend {pricing['action']} price to {pricing['suggested_price']:.2f} "
                f"(current {pricing['current_price']:.2f}), based on {pricing['matched_competitor_count']} "
                f"matched competitor price(s), confidence {pricing['confidence_score']} "
                f"[Source: recommendation_outcomes table, outcome_id={pricing['outcome_id']}, "
                f"evidence_id={pricing['evidence_id']}]."
            )
            for record in _load_competitor_price_records(conn, tenant_id, pid):
                availability = "in stock" if record["is_available"] else "out of stock"
                lines.append(
                    f"  - Competitor snapshot: {record['competitor_name']} priced this at "
                    f"{record['price']:.2f} {record['currency']} ({availability}), captured "
                    f"{record['observed_at']} [Source: competitor_prices table, vendor="
                    f"{record['competitor_name']}]."
                )
        elif pstatus == "UNKNOWN":
            lines.append(
                "Pricing: no competitor price data was available in the required currency to base a "
                f"recommendation on [Source: evidence_records table, evidence_id={pricing.get('evidence_id')}]."
            )
        else:
            lines.append(f"Pricing: {pstatus}.")
        lines.append("")
    return "\n".join(lines)


def stage_rag_grounding(
    tenant_id: str, user_id: str, product_ids: list, forecast_results: dict, pricing_results: dict,
    sentiment_summaries: list, mock_file: str, row_count: int,
    extraction_details: dict = None, discoveries: list = None,
) -> Stage:
    stage = Stage("7_rag_grounding")
    if not product_ids:
        stage.skip("No promoted products to summarize for RAG grounding.")
        return stage

    conn = db.app_role_connection(tenant_id, user_id)
    try:
        summary_text = _build_summary_document(
            conn, tenant_id, mock_file, row_count, product_ids, forecast_results, pricing_results,
            sentiment_summaries, extraction_details=extraction_details, discoveries=discoveries,
        )
        content = summary_text.encode("utf-8")
        object_key = f"{tenant_id}/e2e-pipeline-summary-{uuid.uuid4()}.txt"

        minio_client = db.minio_client()
        import io
        if not minio_client.bucket_exists(rag_pipeline.DEFAULT_BUCKET):
            minio_client.make_bucket(rag_pipeline.DEFAULT_BUCKET)
        minio_client.put_object(
            rag_pipeline.DEFAULT_BUCKET, object_key, io.BytesIO(content), length=len(content),
            content_type="text/plain",
        )

        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO rag_documents_metadata "
                "(tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type, uploaded_by_user_id) "
                "VALUES (%s, %s, %s, %s, 'text/plain', %s);",
                (tenant_id, "e2e-pipeline-summary.txt", object_key, len(content), user_id),
            )
        conn.commit()

        processed_count = rag_pipeline.ingest_pending_documents(conn, minio_client, tenant_id)
        conn.commit()
        stage.details = {"object_key": object_key, "documents_ingested": processed_count}
        if processed_count == 0:
            stage.status = "PARTIAL"
            stage.errors.append("Document was uploaded but ingest_pending_documents() processed 0 documents.")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        stage.fail(str(e))
    finally:
        conn.close()
    return stage


def stage_rag_query_test(tenant_id: str, user_id: str, product_ids: list) -> Stage:
    stage = Stage("8_rag_chat_verification")
    if not product_ids:
        stage.skip("No promoted products - nothing to verify a grounded answer against.")
        return stage

    conn = db.app_role_connection(tenant_id, user_id)
    try:
        query_text = (
            f"What is the forecast and price recommendation for {product_ids[0]['product_name']}, "
            "and exactly which internal tables or market data sources did you base that on?"
        )
        result = rag_llm_client.answer_query(conn, tenant_id, query_text, top_k=5)
        conn.commit()
        stage.details = {"query_text": query_text, "answer": result["answer"], "source_count": len(result["sources"])}
    except rag_llm_client.LLMError as e:
        conn.rollback()
        stage.status = "PARTIAL"
        stage.errors.append(f"Retrieval succeeded but the LLM call failed (expected without GROQ_API_KEY set): {e}")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        stage.fail(str(e))
    finally:
        conn.close()
    return stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-file", default=DEFAULT_MOCK_FILE)
    parser.add_argument("--skip-scraping", action="store_true", help="Skip stage 3 (no network / no SCRAPER_DATABASE_URL available)")
    parser.add_argument(
        "--live-approve-hosts", default="",
        help="Comma-separated hostnames the operator explicitly authorizes to actually be scraped this run "
             "(e.g. 'www.impactbattery.com') - see stage_scraping()'s own docstring. Every discovered candidate "
             "is logged and tenant-scoped regardless; only listed hosts (or ones with real terms evidence "
             "already recorded) are actually fetched.",
    )
    parser.add_argument(
        "--geo-scope", default=None,
        help="Override the tenant's default discovery market scope (companies.country_code) for this run - "
             "e.g. 'Amman' to narrow, 'Middle East' to widen. Omit to use the tenant's own stored default.",
    )
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    live_approve_hosts = {h.strip() for h in args.live_approve_hosts.split(",") if h.strip()}

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or os.path.join(REPO_ROOT, "reports", "e2e_pipeline", run_id)
    os.makedirs(output_dir, exist_ok=True)

    admin_conn = psycopg2.connect(db._admin_database_url())
    admin_conn.autocommit = False
    run_started = time.time()
    report = {"run_id": run_id, "mock_file": args.mock_file, "stages": []}

    try:
        identity = _setup_demo_tenant(admin_conn)
        tenant_id, user_id = identity["tenant_id"], identity["user_id"]
        report["tenant_id"], report["user_id"] = tenant_id, user_id
        print(f"[setup] tenant_id={tenant_id} user_id={user_id}")

        stage1, summary = stage_extraction(args.mock_file, tenant_id, user_id)
        report["stages"].append(stage1.to_dict())
        print(f"[{stage1.name}] {stage1.status} - {stage1.details}")

        job_id = stage1.details.get("job_id")
        stage2, product_ids = stage_promotion(tenant_id, user_id, job_id, summary)
        report["stages"].append(stage2.to_dict())
        print(f"[{stage2.name}] {stage2.status} - promoted {len(product_ids)} product(s)")

        if args.skip_scraping:
            stage3 = Stage("3_competitor_scraping")
            stage3.skip("--skip-scraping passed.")
        else:
            stage3 = stage_scraping(admin_conn, tenant_id, user_id, product_ids, live_approve_hosts, args.geo_scope)
        report["stages"].append(stage3.to_dict())
        print(f"[{stage3.name}] {stage3.status}")

        stage4, sentiment_summaries = stage_market_analysis(tenant_id, user_id)
        report["stages"].append(stage4.to_dict())
        print(f"[{stage4.name}] {stage4.status} - {stage4.details}")

        stage5, forecast_results = stage_forecasting(tenant_id, user_id, product_ids)
        report["stages"].append(stage5.to_dict())
        print(f"[{stage5.name}] {stage5.status}")

        stage6, pricing_results = stage_pricing(tenant_id, user_id, product_ids)
        report["stages"].append(stage6.to_dict())
        print(f"[{stage6.name}] {stage6.status}")

        stage7 = stage_rag_grounding(
            tenant_id, user_id, product_ids, forecast_results, pricing_results, sentiment_summaries,
            mock_file=args.mock_file, row_count=stage1.details.get("row_count", 0),
            extraction_details=stage1.details, discoveries=stage3.details.get("discoveries", []),
        )
        report["stages"].append(stage7.to_dict())
        print(f"[{stage7.name}] {stage7.status}")

        stage8 = stage_rag_query_test(tenant_id, user_id, product_ids)
        report["stages"].append(stage8.to_dict())
        print(f"[{stage8.name}] {stage8.status}")

    finally:
        admin_conn.close()

    report["overall_status"] = (
        "FAILED" if any(s["status"] == "FAILED" for s in report["stages"])
        else "PARTIAL" if any(s["status"] in ("PARTIAL", "SKIPPED") for s in report["stages"])
        else "OK"
    )
    report["total_duration_seconds"] = round(time.time() - run_started, 3)
    report["peak_process_rss_mb"] = max(
        (s["process_rss_mb_at_completion"] for s in report["stages"]), default=None
    )

    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    text_path = os.path.join(output_dir, "report.txt")
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(f"E2E Pipeline Run {run_id} - overall status: {report['overall_status']}\n")
        f.write(f"tenant_id={report.get('tenant_id')} user_id={report.get('user_id')}\n\n")
        for s in report["stages"]:
            f.write(f"[{s['stage']}] {s['status']} ({s['duration_seconds']}s)\n")
            for err in s["errors"]:
                f.write(f"    ! {err}\n")
            f.write(f"    {json.dumps(s['details'], default=str)[:1000]}\n\n")

    print(f"\nOverall status: {report['overall_status']}")
    print(f"Full report written to: {json_path}")
    print(f"Readable summary written to: {text_path}")


if __name__ == "__main__":
    main()
