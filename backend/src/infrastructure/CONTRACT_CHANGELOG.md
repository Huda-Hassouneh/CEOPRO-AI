# KEEL - Infrastructure Contract Changelog

All breaking changes, database constraint adjustments, and API/Event contract modifications between Web-App, Ingestion, and AI/ML teams are strictly tracked here.

## - 2026-07-27
### Added
- Initialized core relational multi-tenancy database schema (`init_schema.sql`).
- Added critical `product_scores` and `campaigns` production tables to database configuration.
- Deployed live asynchronous message broker streaming topics inside Redis (`init_broker.py`).
- Integrated strict `X-Internal-Service-Token` middleware authentication policy (`security.py`).
- Configured automated multi-tenant raw ingestion sample files under `/mocks`.

## - 2026-10-16
### Added (all additive; no existing field, column, or endpoint removed or renamed)
- **DB** — migration `20261016000000_add_competitor_category_and_confidence.sql`: new nullable columns only. `global_competitors`: `category_path`, `address`, `phone`, `rating`, `rating_count`, `place_types`. `tenant_competitors`: `category_similarity`, `confidence_score` (0-100), `confidence_label` (High/Medium/Low), `confidence_reasons`, `confidence_breakdown`, `classification_reason`, `evidence_id` (FK to `evidence_records`, `ON DELETE SET NULL`). Existing rows are valid unchanged (all NULL) until re-scored. RLS policies unchanged; the new columns are covered by the existing per-table policies.
- **API** — `GET /dashboard/competitors`: every existing field and both groups (`strategic`, `relevant`) unchanged, including the exact `summary_line` wording. New per-row fields: `confidence_score`, `confidence_label`, `confidence_reasons`, `confidence_breakdown`, `confidence_summary`, `category`, `category_match_pct`, `address`, `phone`, `rating`, `rating_count`, `distance_km`, `competitor_scope`, `found_via`, `matched_product_count`. New top-level key `possible` (always present, empty unless `separate_weak_leads=true`). New optional query params: `separate_weak_leads`, `min_confidence`, `max_distance_km`, `limit`, `offset` (omitting all of them returns the original shape).
- **API** — new `POST /competitors/reclassify` (tenant-scoped, same auth as `POST /competitors`): re-scores the caller's own competitors.
### Changed (behaviour — consumers should know)
- `GET /dashboard/competitors` ordering: **confidence_score descending** (was alphabetical by name); unscored rows last, alphabetical.
- `tenant_competitors.tier = 'CANDIDATE'` (not tracked) now also means "different business category" (previously only manufacturer / out-of-region). A competitor in a different segment from the tenant (e.g. a donut shop for a burger restaurant) is no longer `is_tracked`, so it disappears from every consumer that already filters on `is_tracked` (dashboard, search, metrics, pricing, MPI, extraction catalog, RAG context/summaries). Manually added competitors and those with >= 60% product overlap are never excluded by category.
- A domain-level find (Places / industry search) is `STRATEGIC` only when its category is in the same segment as the tenant's; related-but-different or unverifiable categories are `RELEVANT` (previously always `STRATEGIC`).
- `global_competitors.competitor_name` for product-search finds is now the seller's hostname (was the product page title). `POST /competitors/reclassify` repairs existing rows.
- Seeded retailer domains (`RETAILER_DOMAINS_BY_VERTICAL`) are only used for tenants operating in the retailer's origin country; operator override: env `RETAILER_INTERNATIONAL_DOMAINS`.
### Spec alignment
- S22: each classification outcome is recorded in `evidence_records` (`source_module = competitor_classification`, `FACT` or `UNKNOWN`), written only when tier/score changes.
- S20: confidence weights are configurable (`COMPETITOR_CONFIDENCE_WEIGHTS`) and every row exposes its per-signal breakdown.
- Data ownership matrix unchanged: competitor data is still written only by the AI Market Scraper Service code path (`discovery.py` / `competitor_classification.py`); the new endpoint calls into that same path.

## - 2026-10-17
### Added (additive)
- **DB** — migration `20261017000000_add_competitor_tracking_decision.sql`: nullable `tenant_competitors.tracking_decision` (`USER_TRACKED` / `USER_UNTRACKED`). Written by the owner's track/untrack action (`discovered_competitors.set_tracked`); NULL for every existing row.
- **API** — `GET /dashboard/competitors` and `GET /competitors/{id}` rows gain `maps_url` and `tracking_decision`. `GET /discovery/competitors`: new `sort=confidence` (competitive confidence, best first; ties by business-is-real `confidence`, then relevance). Each row gains `confidence_score` (0-100, how sure it COMPETES), `confidence_label`, `confidence_reasons`, `category`, `classification_reason`, `tracking_decision`, `maps_url`. The existing `confidence` (0-1, how sure the business is real), `relevance` and all other fields are unchanged. Default sort is unchanged (`relevance`).
### Changed (behaviour)
- `GET /competitors` (flat list): **default order unchanged (alphabetical by name)**; new optional `sort=confidence` orders by `confidence_score` descending (unscored last, then name). Unknown `sort` values are rejected (422).
- Discovery (`market_discovery`) no longer lists a business in a different SEGMENT from the company (e.g. a donut shop for a burger restaurant) unless it has stronger evidence (same products at a published price, or the company's own specialty). Only a positive mismatch excludes; unknown categories are never excluded.
- After every discovery run, competitors are scored (category, competitive confidence, shared evidence record). Re-scoring never starts tracking a competitor that is not tracked, never changes a suggestion's tier, and never overturns an owner's explicit track/untrack choice. It may stop tracking a competitor the SYSTEM tracked if it is in a different category. `auto_track` no longer re-tracks a competitor the owner untracked.
- The Places-nearby discovery path skips permanently closed businesses.
