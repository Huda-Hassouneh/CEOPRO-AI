# Integration guide

> **18 October review update:** the custom competitor bridge and dependent Smart Alerts UI are suspended. The current team competitor source is restored unchanged. Earlier descriptions of active custom tracking below are historical. See [current review instructions](COMPETITOR_REVIEW.md).


## What is implemented

WooCommerce REST v3 polling and Shopify OAuth/GraphQL polling are implemented through a shared stateless Python adapter and Node synchronization infrastructure. Shopify webhooks schedule/coalesce synchronization. WooCommerce webhooks are not implemented. Product/variation identifiers, prices, stock observations, supported order-line sales, invoices and allocated refunds are normalized; customer identities, payment-card data, traffic analytics and arbitrary invoice formats are outside this connector release.

Both stores need `npm.cmd run api:store` and `npm.cmd run worker:store-sync`. Configure STORE_CONNECTOR_API_URL=http://127.0.0.1:8002 in backend, a matching STORE_CONNECTOR_SERVICE_SECRET (32+ characters) in backend and ai, and a backend STORE_CONNECTOR_ENCRYPTION_KEY (64 hex characters). The adapter validates signed tenant-bound requests and bounded responses; it has no independent subscription decisions or PostgreSQL writes. Credentials are encrypted with tenant/source-associated AES-GCM in Node. Back up the stable encryption key securely; changing it makes existing credentials unreadable.

Use the existing **Data Connections → Your Website / Online Store** flow. Store connection registration, canonical writes and schedule updates require the tenant's permissions and plan capacity. Check capacity before importing 192/120 products. Do not change entitlements inside Python or manually seed around capacity checks.

## WooCommerce

1. Have administrator access to the intended WordPress/WooCommerce installation. Confirm actual products/SKUs and currency; inventory tracking must be enabled on the products/variations whose quantities you expect.
2. In WooCommerce → Settings → Advanced → REST API, create a key for an authorized user with **Read** permission. Keep the Consumer Key/Secret private. KEEL asks for them in the connection form; never put tenant store keys into shared server .env files.
3. Use the store's public HTTPS base URL, not wp-admin or a product page. The adapter calls `/wp-json/wc/v3/products`, variations, orders and supported refunds with authenticated requests. A browser homepage alone does not verify REST access.
4. Enter the URL in the existing website flow, confirm WooCommerce detection, submit read-only credentials and start sync. Inspect product progress, source errors and the final sync state.
5. Create fictional orders with real catalog line items/quantities. Mark qualifying orders Completed and check their paid date in WooCommerce. Completed sales and **Paid Invoices** are separate facts: an unpaid or undated order must not be invented as a paid invoice.
6. Sync again. Check product SKU/currency, stock observation, order invoice state and product sales history. Repeat without edits and compare counts: unchanged external IDs must not create duplicate records.
7. Change one product price/stock and create one additional completed order; resync and verify only the corresponding records change. Test supported line refunds separately; unallocated/free-form refund amounts are not silently distributed into product demand.
8. Pause stops future scheduling; resume/Sync now schedules work. Disconnect revokes KEEL's stored credential use while retaining canonical history. Reconnect cautiously: Woo source registration is URL-based, so a changed Quick Tunnel host can register another source rather than preserving identity.

### Local WordPress test store

The previously created test stack is separate from root PostgreSQL/Redis. Its Docker project is `keel-woo-test`, WordPress listens on 127.0.0.1:8088, and its MySQL database is unrelated to KEEL_DEV. Its provisioning Compose file is not included in this source archive; use your existing test stack/configuration.

```powershell
# Use the directory containing that test stack's Compose file.
docker compose -p keel-woo-test up -d
cloudflared tunnel --url http://127.0.0.1:8088
```

Keep cloudflared running. Sleeping/restarting the machine can terminate the temporary hostname. Update WordPress **Address (URL)** and **Site Address (URL)** to the new HTTPS hostname; otherwise login/navigation/REST redirects can point to the dead hostname. Values overridden in wp-config.php take precedence over admin settings. Update KEEL's connection through its supported flow; do not rewrite source IDs/database rows to hide a URL change. Prefer a stable named tunnel/domain for repeatable testing. WordPress coming-soon storefront mode does not by itself prove REST authentication works. Never log or paste the REST secret while testing.

## Shopify

1. Have a Shopify development/test store and permission to install your app. Enter `your-store.myshopify.com` into KEEL; a Dev Dashboard app URL is not the merchant store URL.
2. Create/configure the server's Shopify app. Set backend SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, SHOPIFY_REDIRECT_URI and FRONTEND_URL. Merchant users authorize the installed app; they do not edit server .env.
3. Configure **App URL** and allowed redirect URL in the app configuration/version being installed. Use the same public host for App URL and redirect URI. For local testing expose the backend: `cloudflared tunnel --url http://127.0.0.1:5000`. The callback must be exactly `https://CURRENT-BACKEND-HOST/integrations/shopify/callback`. Whitelist that exact value, without trailing spaces or a different path/scheme. Set FRONTEND_URL to the actual UI origin for the final browser return. The WooCommerce :8088 tunnel is a different service.
4. Use `shopify.app.keel.example.toml` as a registration template, not proof that subscriptions were deployed. Configure scopes **read_products, read_orders, read_inventory, read_locations**. Request read_all_orders only if approved and set SHOPIFY_REQUEST_ALL_ORDERS appropriately; normal read_orders history is limited by Shopify's allowed order window.
5. Start Node API, adapter and store worker. In KEEL choose the shop domain, follow OAuth, review permissions and Install. Node validates state/HMAC and exchanges credentials; reconnect existing sources through the UI to preserve stable Shopify shop identity.
6. Shopify protected customer/order-data access is a separate approval gate. `ACCESS_DENIED path=['orders'] This app is not approved to access the Order object` is not solved by adding read_orders again or changing a GraphQL field. Complete the platform's applicable approval/identity requirements. Deleting orders is not a reliable permission fix. There is no implemented catalog-only sync switch: products may commit before a later orders phase marks the run ERROR.
7. Register/deploy webhook subscriptions in the Shopify app configuration. Node does not automatically create these registrations merely because its receiver exists. Receiver: `/integrations/shopify/webhooks`; raw-body HMAC is checked with SHOPIFY_CLIENT_SECRET, events deduplicated, then relevant sync work is queued. Topics: app/uninstalled; products/create, products/update, products/delete; orders/create, orders/updated, orders/paid, orders/cancelled; refunds/create; inventory_levels/update. Compliance topics: customers/data_request, customers/redact, shop/redact.
8. Run an initial sync and the repeat/update/refund checks below. Product inventory imports need Shopify inventory tracking and actual available quantities at locations; a product CSV without proper inventory settings/location import does not guarantee stock. Test orders are gated to supported development-store behavior; do not count arbitrary test transactions as production sales.
9. On uninstall/disconnect, verify credentials/source scheduling are revoked and history is retained under existing policies. Privacy webhook handling does not mean KEEL stores full customer profiles; it deliberately avoids that import.

When a Quick Tunnel changes, update backend SHOPIFY_REDIRECT_URI, Shopify App URL/redirect whitelist and webhook URLs, redeploy the relevant app version, restart backend and retry OAuth. A stale active app version can retain the previous whitelist even when a draft displays the new value. HTTPS, exact origins and reachable raw webhook endpoints are mandatory in production; use stable domains and managed secrets.

## Store acceptance checks

| Check | Expected evidence |
|---|---|
| Initial products | Source-linked external IDs/SKUs, correct price currency, capacity not exceeded |
| Inventory | Managed products carry observed available quantity; unknown stock is not fabricated as zero |
| Paid invoice | Eligible order with payment evidence/date; correct amount/currency/status |
| Product demand | Qualifying completed order lines become recorded canonical sales for those products |
| Repeat unchanged sync | Same product/order-line identities; no additional transactions/invoices |
| Incremental edit | Price/stock changes update expected records; new completed order adds its lines once |
| Cancellation/refund | Only supported order/allocated line effects; no unsupported invented allocations |
| Errors | Source truthfully exposes partial progress/final error; retry after diagnosis |
| Tenant boundary | Other tenant cannot see source credentials, products, invoices or sync status |

Products alone do not fill sales/paid-invoice metrics or demand history. Demand forecasts use recorded sales rather than competitor tracking. A target-day forecast is not a 7/30-day total. Review sentiment requires actual reviews and analysis; products/orders alone do not populate it. Currency-separated dashboard and comparison policies can exclude incomparable data instead of adding currencies together.

## Other providers

**Stripe:** backend STRIPE_SECRET_KEY and STRIPE_SECRET_WEBHOOK; local `stripe listen --forward-to localhost:5000/stripe/webhooks` supplies a signing secret for that listener. Checkout return is pending until a verified event updates subscription state. If the listener was down, inspect/resend the relevant test event using Stripe's tooling; do not assume the CLI will replay all missed deliveries. Keep live/test catalogs distinct and do not run production bootstraps routinely.

**Model APIs:** Node clients in `backend/src/integrations/ai` use hosted Gradio SSE contracts configured by AI_MODELS_SPACE/AI_MODELS_SPACE_URL and AI_ANALYTICS_SPACE/AI_ANALYTICS_SPACE_URL, plus HUGGINGFACE_ACCESS_TOKEN. Current defaults refer to external spaces, whose deployment/wrapper source and uptime are not verified here. AI_SERVICE_TIMEOUT_MS bounds calls. The separate generic AI_SERVICE_URL client is not a universal substitute. AI_SERVICE_USE_MOCKS must not be enabled in production. No local connector endpoint runs a forecasting model.

**RAG:** upload authorized documents, wait for extraction/index status, ask evidence-backed questions and inspect citations. After deploying the search migration, `npm.cmd --prefix backend run rag:reindex` backfills existing documents when authorized/configured. Reindex repairs searchable text; it does not create a model connection. Failed uploads, missing documents, validation errors and provider unavailability are distinct UI states. Document storage quota uses binary KiB/MiB units.

**Search and market collection:** use permitted product URLs/manual matches or configure supported search providers. SEARXNG_INSTANCE_URL points to an actual running instance (e.g. http://127.0.0.1:8888), not a magic enable flag. Paid providers are optional. No provider can guarantee a matching product exists or that a site permits price collection. Missing sitemap does not preclude direct permitted discovery/category links; site restrictions still apply. No CAPTCHA or authentication bypass is supplied.

**Google Places:** GOOGLE_PLACES_API_KEY (and legacy GOOGLE_MAPS_API_KEY usage) are consumed in Python place discovery; call budgets and provider configuration apply. This is optional business/place candidate discovery, not a completed general social-review synchronization connection or a replacement for confirmed product matching. Do not label this entirely unimplemented, and do not promise that declaring the key creates a merchant review feed. Generic POS/ERP/database source cards are not completed persistent canonical connectors merely because standalone adapters exist.

**Email and storage:** Node supports configured Gmail SMTP or Resend for authentication delivery. Use real authorized sender settings. MinIO is an additional Python storage dependency for documents/generated summaries; the root Compose stack does not start it. Prefer scoped MINIO_ACCESS_KEY/MINIO_SECRET_KEY over root credentials. Python standalone marketing/image providers and billing are retained but are not the canonical Node-backed frontend workflow.

## External requirements checked

Platform requirements can change. Official references checked for this handoff (2026-10-18): [Shopify protected customer data](https://shopify.dev/docs/apps/launch/protected-customer-data), [Shopify access scopes](https://shopify.dev/docs/api/usage/access-scopes), [Shopify app configuration](https://shopify.dev/docs/apps/build/cli-for-apps/app-configuration), [WooCommerce REST authentication](https://developer.woocommerce.com/docs/apis/rest-api/authentication). Account approval, live webhook registration, tunnel reachability and real-store results still require operator verification.
