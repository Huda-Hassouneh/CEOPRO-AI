# CEOPRO Pricing Intelligence backend module

## Scope

This package extracts Pricing Intelligence from the legacy `features` controller into a dedicated functional module while preserving the existing public Node route:

`POST /features/pricing/recommend?product_id=<uuid>`

No Prisma schema change and no migration are required.

## Architecture

`Route -> Controller -> Service -> Repo -> Prisma`

The AI boundary is isolated in `client/pricing.client.ts`:

`Service -> Pricing client -> POST {AI_SERVICE_URL}/pricing/recommend`

The client forwards the authenticated Bearer token because the CEOPRO AI API resolves tenant/user context from that token.

## AI contract used

The implementation accepts only the documented `POST /pricing/recommend` fields:

- UNKNOWN: `status`, `evidence_id`
- OK: `status`, `action`, `current_price`, `suggested_price`, `guardrail_clamped`, `margin_guardrail_clamped`, `matched_competitor_count`, `confidence_score`, `evidence_id`, `outcome_id`

It does **not** read undocumented AI fields such as `market_min`, `market_max`, `market_avg`, `market_median`, or `explanation` from the HTTP response.

## Pricing recommendation table fields

- `current_price`: AI response when status is OK; tenant product record for UNKNOWN.
- `action`: AI response.
- `suggested_price`: AI response.
- `matched_competitor_count`: AI response.
- `market_min`, `market_max`, `market_avg`, `market_median`: backend-derived from canonical `competitor_prices` rows using active/tracked mappings, available exact ALLOWED same-currency observations in the current 30-day window.
- `explanation`: read from canonical `evidence_records.explanation_text` using the `evidence_id` returned by AI. If the evidence row has no explanation, the value is `null`; no explanation is fabricated.
- `confidence_score`, guardrail fields, `evidence_id`, `outcome_id`: documented AI response fields.

The market statistics use every eligible observation in the 30-day freshness window. A latest-only rule was not introduced because the supplied AI progress contract does not define one.

## Backward compatibility

The route remains `/features/pricing/recommend`.

The response retains legacy `clamped` as an alias of documented `guardrail_clamped`. Legacy undocumented `max_change_pct`, `min_margin_pct`, and `floor_price` remain present as `null` rather than being fabricated.

The old pricing route/controller implementation was removed from the shared `features` module to prevent two handlers for the same endpoint.

## Subscription enforcement

The route continues to use `requireEntitlement("ai_pricing")` before invoking AI. After a successful AI HTTP response, `incrementUsage(tenantId, "ai_pricing")` records one recommendation usage, matching the existing feature configuration.

## Tenant isolation

Repository operations run in Prisma transactions and set:

- `app.current_tenant_id`
- `app.current_user_id`

before tenant-scoped queries, matching the current forecasting repository pattern and RLS setup.

## Files

New:

- `src/modules/pricing/index.ts`
- `src/modules/pricing/route/pricing.route.ts`
- `src/modules/pricing/controller/pricing.controller.ts`
- `src/modules/pricing/service/pricing.service.ts`
- `src/modules/pricing/repo/pricing.repo.ts`
- `src/modules/pricing/client/pricing.client.ts`
- `src/modules/pricing/types/pricing.validation.ts`
- `src/modules/pricing/types/pricing.types.ts`

Changed:

- `src/app.ts`
- `src/modules/features/route/features.route.ts`
- `src/modules/features/controller/features.controller.ts`
- `src/modules/features/types/features.dto.ts`

## Verification

A TypeScript transpile/syntax check passed for every new/changed TypeScript file using the installed TypeScript compiler.

A full `npm ci` / `npx tsc --noEmit` run could not be completed in the execution environment because dependency installation timed out. Run these in the project after applying the files:

```bash
npm ci
npx prisma generate --config prisma7.config.ts
npx tsc --noEmit
npm test
```

Then test a real authenticated request against the deployed AI service for both `OK` and `UNKNOWN` pricing responses.
