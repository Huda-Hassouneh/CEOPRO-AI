# CEOPRO Sentiment backend module

## Scope

This package extracts Sentiment Analysis from the legacy shared `features` controller into a dedicated functional module while preserving the public Node routes:

- `POST /features/sentiment/analyze-pending?batch_size=<n>`
- `GET /features/sentiment/summary?subject_type=PRODUCT|COMPETITOR|BUSINESS&subject_id=<uuid>&country_context=<optional>`

No Prisma schema change and no migration are required.

## Architecture

`Route -> Controller -> Service -> AI Client`

The sentiment module does not introduce a sentiment-specific repository because these endpoints do not need direct sentiment-table reads/writes from Node. The metered analyze operation reuses the existing subscription usage repository through the service layer.

## CEOPRO AI API contract

### POST /sentiment/analyze-pending

The client sends `batch_size` as a query parameter and forwards the authenticated Bearer token. The AI response is validated as:

- `status: "OK"`
- `analyzed_count: non-negative integer`

The Node service caps the requested batch to the tenant's remaining `sentiment_analysis` entitlement and increments usage only by the number the AI reports as actually analyzed.

### GET /sentiment/summary

The client forwards:

- `subject_type`: `PRODUCT`, `COMPETITOR`, or `BUSINESS`
- `subject_id`: required by Node for `PRODUCT` and `COMPETITOR`; optional for `BUSINESS`
- `country_context`: optional
- authenticated Bearer token

The response validator accepts only the documented shapes:

- `UNKNOWN`: `status`, `evidence_id`, `sample_size.status = LOW_SAMPLE_SIZE`, `sample_size.minimum_required`
- `OK`: `status`, `evidence_id`, `sentiment_score` (-1..1), positive/neutral/negative label counts, and sample-size metadata

## Subscription enforcement

- `POST /analyze-pending` uses `requireEntitlement("sentiment_analysis")` because it is metered.
- `GET /summary` uses `requireFeatureAccess("sentiment_analysis")` and does not increment usage.

The service retains the existing additional quota cap before calling AI so `batch_size` cannot exceed remaining usage.

## Authentication and tenant isolation

The dedicated router retains the existing `authenticateUser` and `requireTenant` middleware. The AI client forwards the incoming Authorization header because the CEOPRO AI API resolves tenant/user context from the Bearer token.

## Mock support

The client honors the project's existing `AI_SERVICE_USE_MOCKS=true` switch. With mocks enabled:

- summary returns a deterministic valid `OK` payload;
- analyze-pending returns up to 5 analyzed rows, bounded by the requested batch.

This is development-only behavior; setting `AI_SERVICE_USE_MOCKS=false` uses `AI_SERVICE_URL`.

## Legacy cleanup

The old sentiment routes and sentiment controller object were removed from the shared `features` module to avoid two handlers owning the same URLs. `sentimentBatchQuerySchema` was removed from the shared DTO because validation now lives inside the sentiment module. The shared `subjectSummaryQuerySchema` remains because the existing MPI route still uses it.

## Files

New:

- `src/modules/sentiment/index.ts`
- `src/modules/sentiment/route/sentiment.route.ts`
- `src/modules/sentiment/controller/sentiment.controller.ts`
- `src/modules/sentiment/service/sentiment.service.ts`
- `src/modules/sentiment/client/sentiment.client.ts`
- `src/modules/sentiment/types/sentiment.validation.ts`
- `src/modules/sentiment/types/sentiment.types.ts`

Changed:

- `src/app.ts`
- `src/modules/features/route/features.route.ts`
- `src/modules/features/controller/features.controller.ts`
- `src/modules/features/types/features.dto.ts`

## Verification

A TypeScript `transpileModule` syntax check passed for every new and changed TypeScript file.

A full semantic `npx tsc --noEmit` could not be run in this workspace because the materialized backend's `node_modules` tree is incomplete (package directories exist but their installed files/binaries are missing). Run these in your local backend after replacing the files:

```bash
npm ci
npx prisma generate --config prisma7.config.ts
npx tsc --noEmit
npm test
```

## Example dashboard call

For the business-level dashboard sentiment KPI:

```http
GET /features/sentiment/summary?subject_type=BUSINESS
Authorization: Bearer <token>
```

No `subject_id` is required for `BUSINESS`.
