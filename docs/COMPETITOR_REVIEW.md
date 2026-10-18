# Competitor AI restoration — isolated review release

Date: 18 October 2026. This release supersedes the custom competitor integration described in the earlier handoff.

## What is restored

The supplied `latest-teammate keel_test.zip` is the current team source. Its Python `backend/` is installed at `ai/` in this integrated layout. All 169 files under `ai/src/market_scraper/`, plus `ai/src/ai/pricing/competitor_classification.py`, are byte-identical to that archive. No locally added scraper helper remains in that subtree. Run `node scripts/verify-team-competitors.mjs` to verify the saved hashes and exact file set. The archive itself has no Git metadata; `f18afa1` is the commit reported by your earlier fetch, not an independently verified archive commit.

The current team Python source, its requirements, tests and standalone migrations are retained. The team frontend is preserved at `reference/python-frontend/`, and its original deployment files at `reference/python-deployment/`. Those reference files are not the running React/Node application.

## Integration overlays that remain

WooCommerce/Shopify stateless adapters, their requirements and tests; the authenticated Node-facing business-insights API and canonical-sales/evidence adaptations; scoped object-storage credentials; tenant-scoped generated RAG summaries and their isolation tests. RAG changes were combined with the supplied team's latest document/model-version changes; they were not replaced wholesale with the older RAG implementation.

Store response decoding now belongs to `ai/src/ai/connectors/response_text.py`. Store adapters still reuse the team's unmodified public-address guard from `market_scraper/network_security.py`; no custom competitor worker is required by the store service.

`docs/REVIEW_CHANGED_FILES.csv` compares this package with `keel(4).zip`. `docs/AI_REVIEW_OVERLAYS.csv` lists the exact differences between `ai/` and the current team Python snapshot. This is source separation, not a claim that every updated team AI endpoint is verified against the integrated database.

## Disabled dependencies

| Area | Current behavior |
| --- | --- |
| Directory | Existing competitor profiles, historical comparisons and alias editing remain available. |
| Competitor add/track/discovery | Controls hidden; direct API calls return `NOT_IMPLEMENTED` before the repository. |
| Matching and source workflows | Manual URL, preview, confirmation, robots review, approval, collection retry and schedule controls hidden; dependent endpoints blocked. |
| Automatic producers | Product creation no longer requests discovery. Request/scheduler/dispatcher functions return before database/Redis work. |
| Sales-import trigger | New forward migration disables only `sales_import_market_discovery`. Existing data, queue history and RLS remain. |
| Market launchers | Root `workers:market`, `worker:dispatch` and direct backend `worker:market-tracking` exit without connecting to DB/Redis or starting Python. Old Python checker scripts return disabled responses. |
| Smart Alerts | Hidden from navigation, page and actions; direct API blocked. Pending market-alert notifications are acknowledged without generating receipts; old market-alert notifications are excluded from listing/unread count, retained in DB. |
| Pricing | Independent recommendation service and previously stored eligible comparisons remain. This package does not collect new competitor prices. |
| Other services | Store sync, ingestion, business recommendations, RAG, forecasts and other tenant/platform notifications retain their integrations. |

The two capability constants are deliberately false in source. Old `.env` values cannot re-enable the withdrawn bridge. Reconnecting the team's worker protocol requires a separately reviewed implementation; flipping a flag alone is insufficient. Dormant Node/UI modules and historical tests remain in source for reference.

The team's own Python competitor CLI remains unmodified. It is not connected to the Node-owned authorization/subscription/schema contract in this release. Do not run its standalone migrations or worker supervisor against `KEEL_DEV`.

## Applying locally (Windows PowerShell)

1. Stop old market worker and dispatcher terminal processes with Ctrl+C. Stop the backend while applying the migration. An already running process continues using its loaded old code until stopped. Existing Redis streams and database rows are intentionally retained.
2. Extract the package into a separate review folder. Do not overwrite your running project or its secrets. Copy your local environment files privately into the extracted root/backend/frontend/ai locations as needed; this ZIP has examples only.
3. From the extracted `keel` directory:

```powershell
npm.cmd --prefix backend ci
if ($LASTEXITCODE -ne 0) { throw 'Backend install failed' }
npm.cmd --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend install failed' }

# backend/.env BOOTSTRAP_DATABASE_URL must already point to the
# administrative role on your existing KEEL_DEV at 127.0.0.1:5433.
# Runtime DATABASE_URL stays ceopro_app.
npm.cmd run db:migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration deployment failed' }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
npm.cmd run test:competitor-boundary
if ($LASTEXITCODE -ne 0) { throw 'Boundary tests failed' }
```

Migration: `backend/prisma/migrations/20261018180000_suspend_custom_market_bridge/migration.sql`. This is a forward migration; no reset, drop, data deletion or historical migration edit. `db:migrate` deploys all pending Prisma migrations, so review `prisma migrate status --config prisma7.config.ts` from `backend/` first if your local schema differs. This task did not apply anything to your Windows database.

Existing Python environments may need the current team's requirements for their other services. Store-only requirements remain `ai/requirements-connectors.txt`. Start the store API and store-sync worker using the usual `npm.cmd run api:store` and `npm.cmd run worker:store-sync`; keep one instance of each. The public WooCommerce tunnel is separate and must still be running for that test store.

## Verification

See [REVIEW_VERIFICATION.md](REVIEW_VERIFICATION.md) for actual commands/results and limitations. Old custom competitor worker tests still exist but describe the withdrawn bridge; `test:market-tracking` is historical, and is not the active acceptance gate. `test:merge` now runs the disabled-boundary gate instead.

## GitHub review

No remote branch, commit, PR or repository was changed by this task. The ZIP has no `.git` folder.

Your earlier fetch showed a force-updated `origin/KEEL_Test`; the local review branch has divergent ancestry. Do not merge or force-push that old history blindly. Use a separate clean branch based on the current remote when publishing this reviewed snapshot. Do not push directly to `KEEL_Test`. Review the complete diff, especially the layout (`backend` Python becomes `ai`; Node becomes `backend`) and local secrets, before any publication.
