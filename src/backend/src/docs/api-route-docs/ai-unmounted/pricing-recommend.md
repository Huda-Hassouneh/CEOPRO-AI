# AI Pricing Recommendation (Currently Unmounted)

## 1. Endpoint Details

`POST /pricing/recommend`

**Runtime status:** Defined in `modules/features/routes/features.route.ts` but not mounted by `modules/features/index.ts`; currently unreachable through `app.ts`.

## 2. Mental Model

Would proxy a product pricing recommendation to the AI service, then increment the tenant's `ai_pricing` usage counter after a successful response.

## 3. Technical Decisions

The route validates `product_id`, applies `requireEntitlement("ai_pricing")`, calls `AI_SERVICE_URL` with a server-side POST, and exposes a curated recommendation shape rather than the entire AI response. Entitlement middleware is present in the source router, but the router's authentication/tenant middleware is commented out.

## 4. Inputs

- Query: required `product_id: string<uuid>`.
- JSON body: none.
- Headers: no route-local header requirement; intended tenant context is needed by entitlement/usage code.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Pricing recommendation fetched successfully", "data": { "status": "ok", "action": "increase", "current_price": 99, "suggested_price": 105, "clamped": false, "max_change_pct": 10, "min_margin_pct": 20, "floor_price": 90, "market_min": 80, "market_max": 120, "market_avg": 100, "market_median": 99, "matched_competitor_count": 5, "confidence_score": 0.9, "explanation": "...", "evidence_id": "..." } }`.

### Errors

Source controller returns `400 INVALID_REQUEST` for missing product ID, `502 EXTERNAL_SERVICE_ERROR` when the AI service fails, and `500 INTERNAL_SERVER_ERROR` for unexpected failures; entitlement middleware may reject with its own entitlement/usage error.
