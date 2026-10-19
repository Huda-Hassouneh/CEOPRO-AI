# Price Comparison Tiers — architecture plan

Status: **Phase 1 + 2 built and verified (2026-10-19)**; Phase 3 not started. Author: system-architect pass, verified against the code
and contracts listed in §2.

## 1. Problem

A product shows a competitor price only when a competitor sells an item whose **name** matches it
(`market_discovery/offerings.py::best_match`, score ≥ 0.75, price within 0.2×–5× of ours). Everything else
the competitor publishes is discarded. So a business with a "Small beef burger", an "Extra cheese burger" or
a "1 hour class" sees *no comparison at all* when the competitor only lists a "Cheese burger" or a "30 min class",
even though the competitor's price is the most useful reference the owner has.

Target: for every product, show **how it relates** to what competitors sell, in four tiers, so the owner can
read the market even when labels and names differ.

| Tier | Meaning | Example (burger) | Example (language centre, competitor: 30 min = 5 JOD) |
|---|---|---|---|
| `EXACT` | Same product, same size | Cheese burger ↔ Cheese burger | 30 min class ↔ 30 min class |
| `EQUIVALENT` | Same product, different quantity; comparable once scaled | — | 1 hour class ↔ 2 × 30 min = **10 JOD** |
| `SIMILAR` | Same family, different variant/size; a reference, not a like-for-like | Small beef burger ↔ Cheese burger | 35 min class ↔ 30 min class |
| `ADDED_VALUE` | Ours is the competitor's base item **plus something extra**; a higher price can be justified | Extra cheese burger ↔ Cheese burger | Class with conversation ↔ 30 min class |

`direction` records who is richer (`own_richer` / `own_leaner` / `same`) so the UI never says "cheaper" when
the items are not the same size.

## 2. Verification against existing contracts and code

| # | Finding | Decision |
|---|---|---|
| 1 | `competitor_prices` rows are consumed as **exact** data by `pricing/data_access.py`, `price_coverage.py`, `dashboard/competitor_pricing.py`, `price_competitiveness.py` (all assume "same product"). | Similar/equivalent/added-value prices are **never** written to `competitor_prices`. Same reasoning the repo already applied to `market_price_observations` (migration `20261018020000`). A new table holds them. |
| 2 | Competitor items already live in `competitor_intel` (`kind='product'`: name, price, currency, section, description, source_url, retrieved_at). Social-post items need owner verification before feeding prices (`offerings.competitor_items`). | Reuse `offerings.competitor_items()` — same trust filter — as the only input. No new scraping, no new external cost. |
| 3 | `DATA_OWNERSHIP_AND_CONTRACTS.md`: competitor data is written only by the AI Market Scraper Service code path; the `ai` API only reads. | The engine lives in `market_scraper/price_comparison/` and is invoked from `market_discovery/pipeline.py::_match_prices` (the single existing caller of `record_matches`). The API under `ai/` is read-only except an explicit tenant refresh that calls the same engine. |
| 4 | `CONTRACT_CHANGELOG.md`: changes are additive; existing keys and wording stay. | New table, new endpoints, one new key (`competitors.price_ladder`) on `GET /dashboard/products/{id}/intelligence`. Nothing renamed or removed. Entry added to the changelog. |
| 5 | Every tenant table uses `FORCE ROW LEVEL SECURITY` with `tenant_id = get_current_tenant()` and a grant to `ceopro_app` guarded by `IF EXISTS`; migrations ship a rollback in `database/rollback/` when they create tables. | Same pattern. Migration `20261024000000_add_product_price_comparisons.sql` + `.down.sql`. |
| 6 | `pricing/estimation.py` ladder (MARKET_REFERENCE → REGIONAL → PEER → INTERNAL) with capped confidence; spec S19/S20 require estimates to be labelled. | Phase 2 adds one rung, `COMPARABLE_ESTIMATE`, using EXACT-less tiers only, with a lower confidence cap, labelled in the explanation. `ADDED_VALUE` prices are **excluded** from the market average (they would pull a base-price average the wrong way) and only inform a premium note. |
| 7 | Currency policy (spec S19): prices in different currencies are never blended. | Comparison rows are same-currency only (the matcher already skips mismatches); mismatched items are counted, not compared. |
| 8 | AI use: `name_matching.aliases()` already asks the configured model for Arabic↔English names, gated by `DISCOVERY_AI_HINTS`; deterministic matching works without a model. | The tier classifier is **deterministic first** (testable, free, explainable, bilingual EN/AR). A model-assisted adjudicator for ambiguous pairs is Phase 3 and is recorded in `method` (`RULES` now, `AI_ASSISTED` later). No price is ever produced by a model. |
| 9 | Frontend: ProductHub competition panel renders `competitors.product_level`; PricingPage lists products with a recommendation modal; locale files `assets/locales/{en,ar}.json` are checked by `tests/locales.test.mjs` (en/ar key parity). | New `PriceLadder` component reused by both screens; strings added to both locales. |
| 10 | Local environment has no PostgreSQL (docker has no containers); DB integration tests are skipped without `AI_TEST_DATABASE_URL`. | Classification is a pure module with exhaustive unit tests (the two worked examples are test cases). SQL is covered by a DB integration test written to the repo convention; it cannot be executed on this machine and is reported as such. |

## 3. Design

### 3.1 Data model — `product_price_comparisons`
One row per (tenant, product, competitor item): `tier`, `direction`, `match_score`, `scale_factor`
(competitor price × factor = comparable price), `competitor_item_name`, `competitor_price`, `comparable_price`,
`currency`, `price_delta_pct` (ours vs comparable), `reasons` (JSONB list of machine codes + values),
`method`, `source_url`, `observed_at`, `computed_at`. `UNIQUE (tenant_id, product_id, global_competitor_id,
tier)` (the closest item of each tier is kept); FK to `tenant_competitors` and `products` with `ON DELETE CASCADE`. Recomputed per competitor:
rows for that competitor are replaced in one transaction, so a removed menu item disappears.

### 3.2 Classifier (`market_scraper/price_comparison/`)
* `attributes.py` — parse an item/product name (+description) into `core` words, `quantity`
  (dimension `duration|weight|volume|count`, value in a base unit), `size` rank
  (mini/small/regular/large/family) and **modifiers** (`extra`, `double`, `deluxe`, `with <x>`, "مع …", "اضافي",
  "دبل" …). Arabic folding and number words are reused from `offerings.normalize/tokens`.
* `tiers.py` — `classify(own, item)` → `Comparison | None`, in this order:
  1. *Family gate*: core-word overlap (F1 of informative words, one-letter tolerance reused from `offerings`)
     must reach `SIMILAR_MIN` (0.5); otherwise no relation (an unrelated item is never shown).
  2. *Quantity*: same dimension → `ratio = own/item`. Whole multiple within 5 % ⇒ scaled (`EQUIVALENT`, factor =
     ratio). Within ±25 % but not equal ⇒ `SIMILAR` (35 vs 30 min), with a per-unit price delta in the reasons.
     Different dimension or one side missing ⇒ no scaling.
  3. *Modifiers*: ours has extras the item lacks ⇒ `ADDED_VALUE` (`own_richer`); the item has extras we lack ⇒
     `SIMILAR` (`own_leaner`); size words differ ⇒ `SIMILAR` with direction from the size ranks.
  4. Otherwise `EXACT` if overlap ≥ 0.75 (the existing matcher's bar), else `SIMILAR`.
  5. Price sanity: comparable price outside 0.2×–5× of ours is dropped (same bar as `PRICE_RATIO`).
* `premium` — for `ADDED_VALUE`, `premium_pct = (ours − item) / item` and a status against a configurable
  band (`PRICE_COMPARISON_PREMIUM_BAND_PCT`, default 60): `within_range` / `above_range` / `below_base`
  (ours cheaper than a base item that has less in it — flagged as under-pricing). This is a transparent
  heuristic, labelled as such in the UI, not a measured willingness-to-pay.
* `engine.py` — `refresh_for_competitor(conn, tenant_id, competitor_id, products, items)` classifies every
  (product, item) pair, keeps the **best item per tier per product per competitor** (so one menu does not flood the
  ladder), replaces that competitor's rows, returns counts. Called after `record_matches`; never fails the run.

### 3.3 API (read, tenant-scoped, same auth as other `/pricing/*` routes)
* `GET /pricing/comparisons/{product_id}` → `{product, currency, your_price, tiers: {EXACT|EQUIVALENT|SIMILAR|ADDED_VALUE: {count, items[], low, median, high, your_position_pct}}, summary}`.
* `GET /pricing/comparisons?product_ids=a,b,c` (≤ 100) → per product: tier counts, `best_tier`, headline
  position — drives the PricingPage column and coverage strip.
* `POST /pricing/comparisons/refresh` → recompute from stored competitor items for the caller's tenant
  (no external requests, no cost), so existing tenants get tiers without a new crawl.
* The product page does not extend `GET /dashboard/products/{id}/intelligence`; it calls `GET /pricing/comparisons/{id}` directly, which keeps that contract untouched (decision taken during build).

### 3.4 Pricing recommendation (Phase 2)
`estimation.build_estimate` gains `COMPARABLE_ESTIMATE` as its first rung (in-region, same-currency competitor
evidence beats out-of-region references): prices = `comparable_price` of `EQUIVALENT` rows, else `SIMILAR` rows;
confidence cap 0.55 / 0.40; `ADDED_VALUE` rows add a sentence ("your extra-cheese variant sits +40 % over the base
item, inside the usual band") but not a price. Falls through unchanged when no rows exist, so current behaviour and
tests are preserved.

### 3.5 UI
* `PriceLadder` — four tier sections with counts, each row: competitor, their item, their price, comparable price
  with the scaling note ("× 2 of 30 min"), `vs you` %, reason text, source link; premium status for added value.
* PricingPage: per-row **Market position** badge (best tier + % vs comparable) and a **Compare** action opening the
  ladder; a coverage strip (products with exact / equivalent / similar / added-value / none).
* ProductHub competition panel renders the ladder under the existing exact table.

## 4. Phasing
1. **Phase 1** — migration, classifier + engine, hook into discovery, API, contracts, unit tests.
2. **Phase 2** — recommendation rung, PricingPage + ProductHub UI, locales (en/ar), frontend tests.
3. **Phase 3 (not started)** — model-assisted adjudication of ambiguous pairs; owner override ("this is / isn't
   comparable") persisted per pair; premium band learned per category from `recommendation_outcomes`.

## 5. Risks and open questions
* Name-based tiers are heuristic; every row carries its reasons so a wrong call is visible, and `SIMILAR` is never
  blended into the exact market average shown elsewhere.
* The premium band default (60 %) is a product decision — recorded in `PENDING_ACTIONS.md`.
* Quantity parsing covers common EN/AR units (min/hour/ساعة/دقيقة, g/kg/ml/l, pcs); unusual units fall back to
  `SIMILAR` rather than guessing a scale.
* DB integration tests could not be executed locally (no PostgreSQL available).

## 6. Build record (2026-10-19)

Built: migration + rollback; `market_scraper/price_comparison/{attributes,tiers,engine}.py`; hook in
`market_discovery/pipeline.py::_match_prices`; `ai/pricing/comparisons.py` and the three `/pricing/comparisons`
routes; `COMPARABLE_ESTIMATE` rung in `ai/pricing/estimation.py`; `PriceLadder`, `PriceComparisonModal`,
`ProductPriceLadder` and the Pricing page column / coverage strip / refresh button; ProductHub ladder; en + ar strings.

Verification:
* Unit: tiers/attributes/engine (the brief's two examples, unrelated items, Arabic, quantity scaling, premium bands,
  missing table / real DB error handling), ladder shaping and routes, recommendation rung.
* Live PostgreSQL 15 (throwaway container, all 78 migrations applied): 5 DB integration tests, plus a script through the
  real API as the restricted `ceopro_app` role confirming the brief's examples (cheese burger EXACT; small beef burger
  SIMILAR; extra cheese burger ADDED_VALUE +33.3 % within range; 1-hour class EQUIVALENT at 2 x 5 = 10 JOD; 35-minute
  class SIMILAR at 5.83 pro rata), RLS isolation (other tenant: 404 / empty summary) and `/pricing/recommend` returning
  `COMPARABLE_ESTIMATE` for the scaled class.
* Frontend: `npm test` 100/100, eslint clean, production build succeeds.

Known limits (also in section 5): rule-based reading of names; units outside the listed EN/AR set are not scaled.

### Follow-up (same day): the two accuracy limits found in review, fixed
* **Compound spellings** ("cheeseburger" / "cheese burger", "seafood" / "sea food"): `attributes.reconcile_compounds`
  makes both names use the same spelling before anything is compared; a real difference (cheeseburger / cheesecake) still
  does not match.
* **Extra words the rules cannot place** ("conversation class" vs "class"): one name is the other plus words that may be
  an extra or just a variant. Rules no longer guess: the pair is `SIMILAR`, carries `ambiguous` and the reason
  `specificity_unclear`, and is **kept out of pricing recommendations**. `price_comparison/adjudicate.py` asks the
  configured model one strict question (addition or variant) for those pairs only, gated by `DISCOVERY_AI_HINTS`, capped
  at `PRICE_COMPARISON_AI_MAX_PAIRS` (60) per run, cached per pair, never shown or producing a price; the verdict is
  stored (`method = AI_ASSISTED`, reason `ai_judged`) and shown in the UI. Without a model, or on an unclear answer, the
  pair stays unsettled and is labelled as such. Still open: an owner override ("this is / is not an extra"), Phase 3.

### Follow-up: owner override (Phase 3 item, built)
`PUT /pricing/comparisons/{product_id}/override` (owner/admin, `COMPETITOR_MANAGEMENT`): body
`{competitor_id, item_name, verdict: ADDITION | VARIANT | NOT_COMPARABLE | null}`. Stored in
`product_price_comparison_overrides` (migration `20261026000000`, rollback included), keyed by product + competitor +
normalized item name, so it survives every recompute. The engine applies it before the model is asked (owner beats AI,
`method = OWNER`, reason `owner_decision`); `NOT_COMPARABLE` drops the pair before ranking so the next-closest item
fills the tier. The response is the product's recomputed ladder. UI: per-row "It's an extra / Just a variant / Not
comparable / Undo" links in the ladder (Pricing dialog and product page). Verified on live Postgres through the real
API: staff 403; owner ADDITION -> Added value (OWNER) and still there after a full refresh; NOT_COMPARABLE -> uncovered;
null -> back to the system's reading. Still not built: a premium band learned per category (Phase 3).

### Follow-up: hardening pass (same day)
* **AI off the request path.** `POST /pricing/comparisons/refresh` and the override endpoint recompute with rules only
  and answer at once; unsettled pairs are checked by the model in a background task on its own connection
  (`ai_pending` in the response). Earlier AI verdicts are read back from the rows about to be replaced and reused only
  when the side and words are unchanged, so a recompute never re-asks or loses an answer.
* **Speed.** Measured before changing anything: 500 products x 300 items took 8.3 s per competitor. Cached item
  parsing, an exact length bound in the fuzzy word match and a cheap relatedness pre-filter bring it to 0.57 s;
  `test_the_speed_shortcuts_never_change_a_result` proves the output is identical with and without them.
* **Stale rows.** `refresh_for_tenant` now also revisits competitors that have ladder rows but no items left.
* **Rejected prices.** Rejecting a scraped price (`intel_review.review_fact`) now also marks the exact price already
  recorded from it unavailable; before, it kept counting as an exact match and kept feeding recommendations
  (found by checking the review path live; the ladder was clearing correctly, `competitor_prices` was not).
* **Links** from scraped pages are only followed when they are http(s).
* Checked and already fine: correcting or rejecting a price already re-ran matching (and so the ladder) through
  `_match_prices`.
