# CEOPRO MPI Summary Module Implementation

## Goal

Extract `GET /features/mpi/summary` from the shared features controller into a dedicated functional module while preserving the existing public backend route and aligning the external AI call with `CEOPRO_API_Reference`.

## Authoritative AI contract used

The CEOPRO AI API reference defines:

```http
GET /mpi/summary
Authorization: Bearer <token>
```

Query parameters:

- `subject_type`: required string.
- `subject_id`: optional UUID/string identifier.

Response when no usable reviews exist:

```json
{
  "status": "UNKNOWN",
  "evidence_id": "<uuid>"
}
```

Successful response fields:

- `status: "OK"`
- `evidence_id`
- `mpi` in the range `0..100`
- `sample_size.status`: `OK` or `LOW_SAMPLE_SIZE`
- `sample_size.minimum_required`
- `weighted_sentiment_score` in the range `-1..1`
- `volume_confidence` in the range `0..1`
- `review_count`
- `avg_recency_weight`
- `avg_reliability_weight`
- `label_counts.positive | neutral | negative`

The API reference does **not** document a `confidence_score` field for MPI, so the old shared controller's `confidence_score` passthrough was removed.

## Architecture

Implemented:

```text
GET /features/mpi/summary
        ↓
authenticateUser
requireTenant
validateMpiSummaryQuery
requireFeatureAccess("market_perception")
        ↓
mpi.controller
        ↓
mpi.service
        ↓
mpi.client
        ↓
GET AI_SERVICE_URL/mpi/summary
```

No MPI repository was created because this Node endpoint performs no local database read/write. The external AI service owns the MPI computation and evidence creation. The existing `market_perception` boolean feature remains the subscription access gate.

## New files

- `src/modules/mpi/index.ts`
- `src/modules/mpi/route/mpi.route.ts`
- `src/modules/mpi/controller/mpi.controller.ts`
- `src/modules/mpi/service/mpi.service.ts`
- `src/modules/mpi/client/mpi.client.ts`
- `src/modules/mpi/types/mpi.validation.ts`
- `src/modules/mpi/types/mpi.types.ts`

## Modified files

### `src/app.ts`

Mounts the dedicated module at:

```text
/features/mpi
```

The public endpoint remains:

```text
GET /features/mpi/summary
```

### `src/modules/features/route/features.route.ts`

Removed the old shared MPI route to avoid duplicate ownership. Pricing, sentiment and MPI now each have dedicated feature modules.

### `src/modules/features/controller/features.controller.ts`

Removed the legacy `mpiController`. Other feature controllers are unchanged.

### `src/modules/features/types/features.dto.ts`

Removed `subjectSummaryQuerySchema`, which became unused after MPI moved to its dedicated validator. Sentiment already owns its own validator.

## Validation behavior

The dedicated validator preserves the backend's existing subject types:

```text
PRODUCT
COMPETITOR
BUSINESS
```

`subject_type` is required. `subject_id` is optional, matching the MPI API reference rather than the old shared DTO that required it for every request.

Example competitor call:

```http
GET /features/mpi/summary?subject_type=COMPETITOR&subject_id=<competitor-uuid>
Authorization: Bearer <token>
```

## AI client behavior

The client:

- forwards the incoming `Authorization` header;
- uses `AI_SERVICE_URL` with the existing localhost fallback;
- applies a 20-second timeout;
- converts network/timeout/non-2xx failures to a dedicated MPI client error;
- validates both documented `UNKNOWN` and `OK` response shapes before returning them;
- rejects undocumented or malformed AI responses instead of silently accepting them.

The client intentionally does not send `country_context`, because the MPI endpoint in the supplied `CEOPRO_API_Reference` does not document that parameter.

## Mock support

The module honors the existing backend switch:

```env
AI_SERVICE_USE_MOCKS=true
```

With mocks enabled, `GET /features/mpi/summary` returns a deterministic contract-valid MPI response. This is development-only behavior. In production use:

```env
AI_SERVICE_USE_MOCKS=false
AI_SERVICE_URL=<real-ai-service-url>
```

## Error handling

- Missing tenant context uses the backend's existing tenant-access error.
- Missing Authorization uses the existing invalid-auth-header error.
- Invalid query values use `VALIDATION_ERROR`.
- AI network/timeout/non-2xx/contract failures use `EXTERNAL_SERVICE_ERROR` and include `upstream_status` when one exists.

## Database / migration

No Prisma schema change and no migration are required.

## Verification performed

Passed:

- TypeScript `transpileModule` syntax validation for all seven new MPI files and all four modified integration files.
- Static resolution check for all relative imports inside `src/modules/mpi`.
- Verified the old `mpiController` and `subjectSummaryQuerySchema` no longer have references in `src`.
- Verified `/features/mpi` is mounted once in `src/app.ts`.

A full semantic `tsc --noEmit` could not be completed in the materialized workspace because the supplied archive does not include `node_modules`; TypeScript stops immediately because the configured Node type definitions are unavailable.

Run locally after replacing the files:

```bash
npm ci
npx prisma generate --config prisma7.config.ts
npx tsc --noEmit
npm test
```

## Market Intelligence usage

For a competitor row, call the Node backend endpoint using the competitor's UUID:

```http
GET /features/mpi/summary?subject_type=COMPETITOR&subject_id=<competitor-id>
```

When `status` is `OK`, `mpi` is the documented 0-100 Market Perception Index suitable for the `marketPerception` field. When `status` is `UNKNOWN`, the UI should keep market perception unavailable rather than converting it to zero.
