> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# Runtime mounts and frontend contracts

## Python public routes

`backend/src/ai/main.py` mounts routers directly. Prefixes are declared in each router. Effective module dependencies are on include_router, not only on each decorator:

| Router | Mounted gate / caller requirement | In-scope relationship |
|---|---|---|
| auth | Public login/signup/token/verification plus authenticated session/workspace handlers | Keep Python identity issuer |
| billing | Handler tenant context and owner/admin/accountant for mutations/invoices; plans public; webhook raw signature | Only subscription/Stripe authority |
| pricing | No include_router module gate; tenant dependency only in handlers | Gap PRICE-001, both recommend and recommend-all |
| mpi, sentiment | requires(market_intelligence), plus tenant handler | All three scopes; separate Node right is policy conflict |
| extraction | Handler tenant context + extraction reserve; no global module gate | Manual upload/templates/import history/process pending |
| onboarding | Handler tenant context; role checks connect/source mutations | Generic API/database only; dedicated stores missing |
| products, sales, reviews, settings | Tenant handler/role/capacity logic | Canonical matching, stock, invoices, reviews, seats, invitations |
| dashboard | Individual dependencies, including repaired product forecast alias | Pricing/import/MPI read-model dependencies; inspect write aliases |
| forecasting | requires(demand_prediction) | Preserve algorithm; gate all aliases |
| competitors, competitor_enrichment, discovery | requires(competitor_management), with separate credits gates in enrichment | Approved market inputs and source protections |
| rag, marketing, reports, alerts | Existing local quota/provider/status guards | Python-only behavior retained; shared quotas/security coverage |

`evidence/ACTIVE_PYTHON_ROUTES.csv` records each router decorator/handler, prefix and main mount line. It is a source-derived route inventory, not a live OpenAPI export; full app startup needs the complete model dependencies. `ROUTE_CANDIDATES.csv` is a broader declaration/client search, not an active endpoint count.

## Active Node reference entrypoints

`backend/src/server.ts` → `app.ts`. app.ts mounts `/auth`, `/onboarding`, `/platform-admin`, `/subscription`, `/features/pricing`, `/features/mpi`, `/features/sentiment`, `/features/rag`, root feature/dashboard/forecast/dataconnection routers, products and competitors. Stripe webhook is mounted before JSON body parsing; Shopify public callback/webhooks under `/integrations/shopify` also require raw-body handling. `subscription/index.ts` imports singular `plans.route.ts`, `promo-codes.route.ts`, `subscriptions.route.ts`, `invoice.route.ts`, `custom-plan.route.ts`, and exports stripe-webhook.route.ts. `dataconnection/index.ts` mounts `/data-connection`; dataconnection.route.ts mounts `/store`.

Plural `.routes.ts`, route/index.ts and External Services duplicates cannot all be assumed active. `app.ts` imports updateSubscriptionCancellation from the old External Services stripeService, but its direct invocation is commented; this is module reachability, not an active cancellation call. `REACHABILITY.csv` classifies best-effort static import reachability, preserving unverified candidates. No legacy duplicate is ported solely by name.

Read-only store provider API: Node AI connectors/app.py receives internal `/provider`, signed tenant/body hash service token via middleware; normalizers under Shopify/Woo/orders/inventory/transport. Its pure behavior is reference evidence, not a second final authority.

## UI-to-API compatibility ledger

| Python UI/client | Actual contract | Required extension |
|---|---|---|
| features/auth/api/authApi, authHttpAdapter, authContracts; sessionKeeper | access_token/token_type/expires_in/tenant_id/user_id/role_key and 409 workspaces; X-Auth-Reason | Preserve response/storage/refresh; add operator context under same identity |
| features/billing/api/billingApi.js; PlansSubscriptionPage | PlanChoice plan_key/period_code; subscription camelCase; detail.reason for errors; credits and raw features | Promo/custom/quote/platform UI plus approved missing grant/usage keys |
| features/data-connections/api/dataConnectionsApi.js; ConnectDataPage | GET /extraction/imports and /onboarding/sources; POST connect/api or database; source sync/delete | Dedicated store/OAuth, typed invoice/inventory previews and row/error/status details |
| Python ingestion upload clients (evidence client call rows) | Multipart /extraction/upload; rows_processed and promotion counters | Preserve sales summary; version/add optional job/read/review state fields |
| features/pricing/api/pricingApi.js and PriceRecommendationModal | POST /pricing/recommend with product_id query param and null body; action/explanation/market/demand fields | Backend gate/request key, evidence/history and truthful unavailable/retry state |
| market-intelligence competitor/sentiment UI | Aggregated sentiment/comments/data completeness; no direct /mpi/summary frontend call found | Add three-scope MPI client/selectors/states; preserve existing views |
| features/settings and workspaces | Invitations/team roles/sessions/company; active workspace switching | Preserve Python role keys and owner guards; no tenant admin→platform escalation |

Node UI reference: CustomPlanBuilder/CustomPlanQuoteManager/CustomPlanOfferPage, onboarding custom plan page; market-intelligence pricing/mpi APIs; connected data/store forms; platform-admin screens. These establish missing customer/operator journeys; do not transplant whole Node frontend or preview mock values.

## Error and state contracts

Keep Python HTTPException detail.reason/message for billing/usage, 402 feature allowance body including remaining/reset cycle/end, 401/403 identity/permission, 404 tenant-hidden resources, 409 idempotency/revision conflicts and 422 typed invalid requests. Existing Node `{success,code,data,message}` envelope is reference behavior; final Python clients retain Python envelope. Preserve provider failure distinction 502/503 and missing configuration rather than fabricated outputs. Extend UI for pending/review/partial/stale/insufficient states explicitly; unknown numerical result is not zero.
