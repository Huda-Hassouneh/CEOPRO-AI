# Backend

> **18 October review update:** the custom competitor bridge and dependent Smart Alerts UI are suspended. The current team competitor source is restored unchanged. Earlier descriptions of active custom tracking below are historical. See [current review instructions](../docs/COMPETITOR_REVIEW.md).


Express 5/TypeScript with Prisma 7's pg adapter. `src/server.ts` starts HTTP; `src/app.ts` mounts routes and raw webhook parsers; `src/config/database.ts` creates the restricted application client. Prisma schema, forward SQL migrations, bootstrap utilities and optional demo seeds live in `prisma/`.

## Responsibilities and routes

| Module | Responsibility / API prefix |
|---|---|
| Auth / onboarding | Registration, email checks, sessions, tenant memberships; `/auth`, `/onboarding` |
| Platform administration | Verified platform staff, tenants/plans/permissions; `/platform-admin` |
| Subscription | Stripe-backed plan lifecycle, entitlements and usage; `/subscription`, raw `/stripe/webhooks` |
| Data connections / ingestion | Source registration, extraction staging, canonical promotion; `/data-connection` |
| Products / competitors | Merchant catalog, GTIN, candidate review, approval and monitored sources; `/products`, `/competitors` |
| Features | Pricing, recommendations, alerts, sentiment, MPI and RAG under `/features/*` |
| Notifications | Recipient-scoped inbox/preferences; `/notifications` |
| Store integration | `/data-connection/store/*`; raw Shopify receiver and OAuth under `/integrations/shopify` |

Repositories set transaction-local tenant/user context before protected queries. RLS and permission/entitlement checks are complementary; do not remove either. Runtime ceopro_app is distinct from migration/bootstrap and dedicated worker roles. Credentials never belong in frontend env. External calls are bounded and validated; store HTTP runs outside transactions, then page commits persist source-scoped identifiers. Business recommendation evidence and comparable prices are validated before consumption/charging. A failed/unusable pricing result does not consume a recommendation credit.

## Run and validate

From root follow [Development](../docs/DEVELOPMENT.md); it handles missing env files, administrator-only migrations and runtime role passwords. Use root launchers for workers because they resolve Python paths relative to the repository.

```powershell
# From backend:
npm.cmd run dev
npm.cmd run prisma:validate
npm.cmd run build
npm.cmd run test:routes
npm.cmd run test:security
npm.cmd run test:market-tracking
npm.cmd run test:store-connectors
npm.cmd run test:rls:isolated
```

See package.json for isolated, source-contract, browser and live suites. A script named `test:...:rls` or `...:worker` can be a source-contract check; the name does not prove it exercised a live restricted PostgreSQL connection. Live database tests require appropriate test URLs/fixtures. `prisma:migrate:test` is the historical name for forward `prisma migrate deploy`; it does not reset the database.

Structured application errors preserve stable codes; worker logs summarize durable job states. Do not log access tokens, store credentials, full URLs containing passwords, document text or customer data. API `/health` is liveness only. For production compile `dist`, run one admin migration deployment job and start `node dist/server.js` under a restricted account; independently supervise the processes in [Workers](../docs/WORKERS.md).
