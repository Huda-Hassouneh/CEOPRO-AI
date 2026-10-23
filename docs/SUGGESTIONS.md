# KEEL - suggestions: pitfalls, gaps, cost and token savings

Review of the code, schema and docs as of 2026-10-23 (commit 041f9f2). Each item names where it was
found. Priority: **P0** before any paying customer, **P1** before scaling past a pilot, **P2** worth
doing soon. Effort: S (≤1 day), M (a few days), L (a week or more).

## Summary

| # | Suggestion | Priority | Effort | Pays off in |
|---|---|---|---|---|
| 1 | Rotate every credential found in public git history | P0 | S | security |
| 2 | Bring the staging API back up and run one live check per external service | P0 | S-M | trust |
| 3 | Shared market database: discover and enrich each real business once, reuse it for every company | P1 | L | data cost, speed, moat |
| 4 | Snap discovery searches to a grid and keep the cache ≥ 7 days | P1 | S | data cost |
| 5 | Move the in-process LLM caches into Redis / Postgres | P1 | S | tokens |
| 6 | Cache the assistant's public web research and lift its 30 searches/day server cap | P1 | S | answers, data cost |
| 7 | Trim the assistant prompt and its retry rounds; keep a cache-friendly prefix | P1 | M | tokens, throughput |
| 8 | Paid LLM tier (or a second key) before launch | P0 | S | throughput |
| 9 | Run the background workers somewhere (they are commented out on staging) | P0 | S | core promise |
| 10 | Scheduled competitor price refresh (G7) | P1 | M | core promise |
| 11 | Licence class on every collected fact (Google, YouTube, Apify, OSM, websites) | P1 | M | legal |
| 12 | One beachhead market | P1 | - | cost, quality, moat |
| 13 | One source of truth for plan limits in the docs | P2 | S | sales clarity |
| 14 | Credits that never make a feature look broken | P2 | M | retention |
| 15 | Smaller token fixes (JSON mode, wasted planner calls, per-URL news) | P2 | S | tokens |
| 16 | Fix stale docs on tenant isolation and run the isolation probe | P1 | S | security |

---

## 1. Heavy, avoidable data and token spend

### 3. Shared market database (biggest single saving)

**What happens today.** The schema already has a shared competitor table
(`global_competitors.visibility = 'GLOBAL'`, `Final_schema.sql:308`), but the code never uses it:

- Discovery always stores a competitor as `PRIVATE` to the company that found it
  (`market_scraper/discovery.py:277`, `market_discovery/pipeline.py:290`,
  `competitor_enrichment.py:258`). Twenty cafés in one district store - and pay for - the same
  neighbouring café twenty times.
- Every fact about a competitor is stored per company: `competitor_sources`, `competitor_enrichment`,
  `competitor_intel` (products and prices read from its website), `market_news`
  (unique per company and URL), reviews and their sentiment, YouTube comments, and
  `market_price_observations`.
- Google Places details and reviews (`competitor_enrichment.py:146`, `_places_get`) have no cache.
  Website crawls, menu OCR and Gemini vision reads (`market_discovery/menu_media.py:366`), Apify and
  ScrapeCreators runs repeat for every company tracking the same business.
- YouTube comment searches share one daily quota for the whole server (`youtube_quota.py`), so
  repeated searches for the same competitor crowd out other companies.

**Why it matters.** The Standard plan's Data budget is $4.37/month
(`docs/SUBSCRIPTIONS_AND_CREDITS.md` §3). `docs/PLAN_LIMITS_FEASIBILITY.md` §2 finds Google's free
1,000 calls/month cover only ~23 Starter or ~7 Growth customers. Today the cost scales with
*companies × competitors*; with a shared layer it scales with the *distinct businesses in a market*,
and every new customer makes the data fresher for the others.

**Design.**

- Shared layer (no `tenant_id`, readable by every company, written only by workers):
  - `market_entities`: one row per real business. Identity: OSM/Overture id, Google `place_id`,
    `website_identity_key` (already computed), or normalised name + geohash-7.
  - `entity_facts`: profile, website products and prices, menu OCR, social links, public comments,
    news - each with source, `fetched_at`, `expires_at` and a licence class (item 11).
  - `area_scans`: (geohash-6 cell, category key) → entity ids, `scanned_at`. A new company in an
    already-scanned area gets its competitor list at once; only stale cells are re-queried.
  - `llm_memo`: `hash(model, prompt)` → answer, for deterministic helper calls (item 5) and per-competitor
    comment themes.
- Private layer (unchanged, RLS-scoped): `tenant_competitors` keeps tracking, aliases, relevance to
  *this* company, notes, comment actions, and all of the company's own products, prices and sales.
  Nothing in the shared layer may reveal which companies use KEEL or whom they track (no
  "requested by" columns readable by tenants; refresh demand counted, not attributed).
- Billing: charge Data Credits only for a real outside call; a shared-layer hit is free or a flat small
  amount. This both improves margin and stops credits running out on data that already exists.
- Freshness: a fact past `expires_at` is served marked stale and queued for refresh by the first
  company that needs it.
- Migration path: keep `global_competitors` as the entity table (switch new rows to `GLOBAL` with a
  dedup key), add `entity_facts`, then point enrichment readers at it facet by facet.

### 4. Discovery cache that actually hits (quick win)

- `market_discovery/http.py:16` caches provider answers in Redis for **24 h**, but discovery re-runs
  every **7 days** (`market_discovery/refresh.py:27`), so the scheduled re-run never hits the cache.
- The key is the exact URL/body, i.e. the exact latitude, longitude and radius. Two shops 300 m apart
  never share an answer.
- Fix: set `DISCOVERY_CACHE_TTL_SECONDS` to ≥ 7 days (for providers whose terms allow it), and round the
  centres produced by `google_places.tiles()`, the OSM and Overture queries to a fixed grid
  (e.g. 0.01° ≈ 1 km) with the radius rounded up, so neighbours produce identical requests.

### 5. LLM helper caches that survive and are shared (quick win)

These are plain Python dicts: lost on every restart, not shared between the API and the five worker
processes, so the same question is paid for again and again.

- `market_discovery/offerings.py` `_ALIAS_CACHE` (Arabic ↔ English product names, e.g. mansaf ↔ منسف)
- `market_discovery/relevance.py` `_TERMS_CACHE` (specialty words)
- `market_discovery/pipeline.py:143` `_CATEGORY_WORDS_CACHE`
- `price_comparison/adjudicate.py` `_CACHE` ("addition" or "variant")

Fix: one helper `memo(namespace, key, fn, ttl)` backed by Redis (Postgres `llm_memo` as the durable
copy). Their answers do not depend on the company, so they are safe to share.

### 6. Assistant web research: no cache, tiny server-wide budget

- `ai/research/research.py:196` calls `web_search.search()` directly. Unlike
  `web_product_discovery.py` (which uses the 7-day `web_search_cache`), research results are never
  cached, so the same public question ("customs duty on olive oil in Jordan") is searched again by
  every company.
- `RESEARCH_DAILY_SEARCH_LIMIT` defaults to **30 searches per day for the whole server**
  (`research.py:43`, 12 per company). With up to 3 queries per question, about ten research questions
  a day exhaust it for everyone; later questions get "budget exhausted".
- Fix: check `web_search_cache` before reserving quota (a hit costs nothing and uses no quota), key on
  the normalised query + country, and size the daily cap from the paid search plan. Pages are already
  shared through `research_pages`; results should be too.
- `plan_queries()` asks the model for queries before the budget check, so an exhausted budget still
  spends a model call. Check the budget first.

### 7. Assistant prompt size and retry rounds

- The fixed part of every assistant prompt - `llm_client.SYSTEM_PROMPT` (~7.8k characters) plus
  `citations.DRAFT_CONTRACT` (~3.5k) - is ~11.3k characters, about 2,800 tokens, before any evidence
  or history. `PLAN_LIMITS_FEASIBILITY.md` still budgets 1,550-1,750 prompt tokens per question.
- `advisor._draft` (`rag/advisor.py:926`) can send the whole prompt up to three times: the draft, a
  format retry, then a repair round. Each repeat re-sends system prompt, evidence and history.
- Fixes:
  - Shorten the two fixed texts (de-duplicate rules the validator already enforces in code).
  - Run the repair round only for issues that change what the user sees (wrong numbers, uncited
    figures), not for cosmetic ones; log `repaired` rates (the log line exists) and watch them.
  - Keep the fixed prefix byte-identical and first, so a provider's prompt caching can apply
    (confirm Groq's current support for the chosen model and record a `cache_read_token` price,
    `SUBSCRIPTIONS_AND_CREDITS.md` §4).
  - Update the per-question token estimate in the feasibility doc and the assistant's reservation.

### 15. Smaller token and data fixes

- `ai/market_inputs/competitor_analysis.py:192` re-sends the full evidence prompt when the JSON is
  malformed; pass `json_mode=True` as the advisor does.
- `market_news` is unique per (company, URL): store each article once and link it to companies.
- Comment theme grouping and sentiment for a competitor's public comments can be computed once per
  competitor (shared layer), not once per company tracking it.

---

## 2. Critical gaps

### 1. Exposed credentials (P0)
The repository is public and 16 of 17 credential values are in git history
(`docs/FINAL_SYSTEM_AUDIT.md` §3.1). Rotate every one before customer data goes in; deleting history
does not undo the exposure.

### 2. Staging API down, external services never checked live (P0)
`keel-ai-staging` `/health` does not answer (`FINAL_SYSTEM_AUDIT.md` §3.2). Stripe, SMTP, OpenStreetMap,
Google Places and search, Apify, reading competitor websites, R2 and the Docker images are covered only
by tests on recorded response formats (`CURRENT_STATUS.md`, Known limits). One live run per service on
staging is the gate before selling.

### 8. LLM throughput (P0)
The free Groq key gives about 3 assistant questions per minute *for all customers together*
(`PLAN_LIMITS_FEASIBILITY.md` §2; replies of 9-16 s under load in `CURRENT_STATUS.md`). Item 7 helps,
but launch needs the paid tier or a second provider in `LLM_PROVIDERS`.

### 9. Background workers not running (P0)
`render.yaml` comments out `keel-workers-staging` because it needs a paid plan. Without it there is no
discovery refresh, enrichment, comment refresh, sentiment or image queue - the "daily decisions" the
product promises. Budget the worker (or a small VM) as part of launch cost.

### 10. Scheduled competitor price refresh (G7)
Still open (`PLAN_LIMITS_FEASIBILITY.md` §3): competitor prices refresh only when someone asks
(`enrichment_worker.py`, `MODE_PRICES`). "Which competitors moved" needs a schedule; with the shared
layer (item 3) one refresh per business serves every company.

### 16. Tenant isolation: stale docs, untested on staging
The API connects as the restricted `ceopro_app` role with per-request tenant context (`ai/db.py`), so
`backend/RED_FLAGS.md`'s "everything connects as a superuser" entry is out of date and should be
updated. But `FINAL_SYSTEM_AUDIT.md` §3.4 says the isolation probe (two companies, every ID-taking
endpoint, every `tenant_id` table as `ceopro_app`) has not been run on staging. Run it, and confirm
which workers use `db.system_connection()` (bypasses RLS) and that each one filters by tenant itself.
This becomes more important once the shared layer (item 3) mixes shared and private tables.

---

## 3. Business pitfalls

### 11. Licences of collected data
- Google Maps Platform terms restrict storing Places content other than `place_id`, and showing it
  away from Google's services; reviews kept 30 days and shared across companies would breach them.
- Apify's Google Maps actor scrapes Google - a terms risk for the business, not only for Apify.
- YouTube API data has retention and refresh rules (comments are already kept 30 days).
- Reviewer and commenter names are personal data (e.g. Jordan's Personal Data Protection Law 2023).
- So: tag each fact with a licence class (`shareable`, `tenant_only`, `id_only`). Build the shared
  layer on OpenStreetMap (ODbL, attribution), Overture, and businesses' own public websites; share only
  `place_id` for Google and re-fetch per company where its terms require.

### 12. "Any business, anywhere" spreads data thin
Discovery rules, taxonomies and Arabic/English matching are strongest for restaurants and cafés in
Jordan. Picking one beachhead (e.g. food & beverage in Amman) maximises overlap in the shared database,
lowers cost per customer, improves match quality and builds a data moat; expand city by city.

### 13. Two different plan tables
`PLAN_LIMITS_FEASIBILITY.md` lists products 250 / 2,000 / 10,000 under Starter / Growth / Enterprise;
`SUBSCRIPTIONS_AND_CREDITS.md` lists 100 / 250 / 500 under Standard / Plus / Pro. The database is the
truth (`usage_plan_limits`); mark the older doc as superseded so sales and support quote one set.

### 14. Credits that make features look broken
"Data Credits" are abstract for a shop owner; when they run out, discovery and enrichment refuse and
screens go empty. With the shared layer, serve existing facts free and show "refreshes on <date>"
rather than an error; warn at 80 % with what it means in plain words ("about 3 more competitor checks").

### Margin at full use
`PLAN_LIMITS_FEASIBILITY.md` §4 projects 17-35 % margin for full-use customers on 6-month prepaid
plans. Per-company data fetching (item 3) and repeated prompts (item 7) are the main drivers; fix them
before discounting further.

---

## Suggested order

1. Items 1, 2, 8, 9 (launch blockers).
2. Quick wins 4, 5, 6, 15 (days, immediate savings).
3. Item 16 (isolation probe), then item 3 with item 11 designed in, then item 10 on top of it.
4. Items 7, 12, 13, 14.
