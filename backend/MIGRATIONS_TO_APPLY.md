# Migrations to apply to staging and production

Covers pending actions #67, #81, #90, #105, #108, #112, #120. Apply **with or before** the code. Files live in
`src/infrastructure/database/migrations/`; each has a rollback in `src/infrastructure/database/rollback/` where noted.

## How

```bash
# Superuser / schema-owning role (never ceopro_app). Safe to re-run: applied files are tracked in schema_migrations.
DATABASE_URL=postgresql://... APP_DB_PASSWORD=... python scripts/apply_migrations.py
```

Take a backup first. Run staging, check, then production.

## Order (filename order, which the runner uses)

| # | Migration | Pending | If missing | Notes |
|---|-----------|---------|------------|-------|
| 1 | `20261018000000_add_competitor_enrichment` | #67 | enrichment jobs fail | |
| 2 | `20261018010000_add_enrichment_sweep_function` | #67 | weekly sweep fails | |
| 3 | `20261018020000_add_market_price_observations` | #67 | price observations lost | |
| 4 | `20261019000000_add_competitor_news_and_comment_facets` | #67 | news / comments facets fail | |
| 5 | `20261019010000_add_comment_retention` | #67 | | |
| 6 | `20261020000000_keel_subscriptions_and_credits` | #67 | billing / credits endpoints fail (~120 tests) | |
| 7 | `20261021000000_pro_plan_limits_500_products_50_seats` | #67 | wrong Pro limits | |
| 8 | `20261022000000_free_image_provider_cost_rows` | #81 | image calls refused (no price row) | Not yet run on a copy of real data; also see #79 |
| 9 | `20261023000000_add_competitor_intel_review` | #90 | `POST /discovery/competitors/{id}/intel/review` errors | Reads/saves tolerate its absence |
| 10 | `20261024000000_add_product_price_comparisons` | #105 | price ladder empty | Rollback only drops derived data |
| 11 | `20261025000000_add_review_source_url` | #112 | comments list errors | Nullable column |
| 12 | `20261026000000_add_comment_action_status` | #112 | comments list errors | Nullable column |
| 13 | `20261026000000_add_price_comparison_overrides` | #108 | owner corrections cannot be saved | Rollback loses saved decisions |
| 14 | `20261026010000_add_comments_refresh_function` | #112 | weekly comments refresh fails | |
| 15 | `20261026020000_add_competitor_review_index` | #112 | slower review lookups | Build off-peak on a very large `reviews` table |
| 16 | `20261027000000_add_price_premium_band_overrides` | #120 | saving an owner-set band errors | Rollback loses owner-set bands only |
| 17 | `20261118000000_add_market_menus_facet` | - | "Read delivery apps & menu photos" errors; vision reads refused (no price row) | Widens the facet check; vision price rows stay NULL until an operator prices them |
| 18 | `20261119000000_set_groq_gpt_oss_20b_price` | `docs/CHATBOT_FIX.md` | **the assistant never writes an answer — it only lists retrieved evidence, even with a valid `GROQ_API_KEY`** (the billing gate refuses the model call while the Groq price is NULL) | Sets Groq's list price for `openai/gpt-oss-20b`; override anytime with `scripts/billing_admin set-price`. No app restart needed (price is read per request) |

## After applying

1. `schema_migrations` lists all 17 (`SELECT version FROM schema_migrations ORDER BY 1 DESC LIMIT 20;`).
2. Call `POST /pricing/comparisons/refresh` once per company (#106).
3. Confirm the cost rows in #97 exist, then spot-check one competitor profile and the Pricing page.
