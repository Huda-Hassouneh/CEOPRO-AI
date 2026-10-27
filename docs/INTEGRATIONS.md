# Local integrations

A healthy local runtime does not imply that external providers are configured. Setup creates no merchant connections, financial cost schedules, Stripe objects or customer subscriptions.

## Shopify and WooCommerce

Reuse the tenant connection screens, `src.market_scraper.provider_store_sync`, source lifecycle/vault and connector worker. Shopify OAuth/webhook configuration uses the actual Python onboarding endpoints; WooCommerce uses the tenant's store URL and approved API credentials.

Use authorized sandbox/test stores. Connection verification must succeed before Connected is shown. Initial/incremental sync stages provider records; manual review and approved canonical services manage promotion. Inventory requires explicit owner source/field/location mappings. Conditional automatic catalog promotion is disabled by default and retains its disposable-test restriction. Automatic invoice posting remains policy-blocked.

Shopify privacy intake authenticates exact-body signatures and shop/topic/source binding. Targeted irreversible privacy erasure/retention decisions remain tracked separately; local startup does not certify them.

Controlled fixture/worker/database evidence exists in the integration acceptance reports. **Real Shopify/WooCommerce merchant E2E is not certified by this developer setup.** Do not copy live merchant credentials into development.

## Stripe TEST MODE (optional)

For optional, isolated lifecycle simulation see the [local Stripe Test Clock guide](STRIPE_TEST_CLOCK_LOCAL_GUIDE.md). Disabled by default; not part of production deployment.

The existing Python billing authority owns Products/Prices, promotions, quotes, Checkout, signed webhook reconciliation, entitlements and Credits.

Configure only an authorized `sk_test_` / `rk_test_` key and the real `whsec_` signing secret from your listener in private `.dev/integrations.env`. Restart after changes. The launcher refuses LIVE keys and incomplete signing configuration.

The actual webhook endpoint is `POST /billing/webhook`. In a separate terminal, use your installed Stripe CLI and an explicit event selection, for example:

```text
stripe listen --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed --forward-to http://127.0.0.1:<printed-api-port>/billing/webhook
```

Authenticate against your authorized TEST account first; inspect local `stripe listen --help` for the installed CLI version. Copy its listener-specific signing secret only into private configuration. Do not fabricate signatures, paste secrets in issues or start real payments as a setup smoke test.

Prior Stripe acceptance is historical evidence; no Stripe E2E is rerun by `dev.ps1 test`.

## AI and market providers

- `setup --models` installs the existing CPU/model libraries. Model weights may download from their actual hosts on first use. The launcher never substitutes dummy predictions.
- Hosted LLM/image/search credentials belong in `.dev/integrations.env`. Read `backend/KEYS_AND_ACCOUNTS_NEEDED.md` and `docs/SUBSCRIPTIONS_AND_CREDITS.md`.
- Configured credentials alone do not authorize spending. Verified cost schedules, entitlements, Credits and reservation/settlement rules still apply.
- Without confirmed financial inputs, pricing/paid operations remain unavailable with their existing messages. No fabricated rates/margins are inserted.
- SearXNG, local LLM/image servers and telemetry exist in the legacy Compose topology but are optional. They are not started as hidden prerequisites by the new local command.
- Browser-assisted scraping needs `python -m playwright install chromium` in the developer venv and may need OS dependencies. It is unnecessary for ordinary startup.
- OCR requires the Tesseract binary/language packs on PATH; without it the existing code reports unsupported/skipped OCR rather than invented extraction.

## Storage and email

Local MinIO uses the existing `src/infrastructure/Dockerfile.minio`, persistent per-checkout volume, generated credentials and loopback console/API ports. It is built from the repository's pinned source recipe; first startup needs registry/Go-module network access. Object buckets/prefixes are managed by existing application code.

Mailpit is a dedicated local SMTP capture and inbox, included by default so OTP/signup works without sending mail externally. Messages may contain synthetic PII and codes; keep the inbox local. No real SMTP account is configured or overwritten.

## Optional service boundaries

External AI, merchant stores, Stripe CLI, model weights, OCR binaries, scraper browser binaries, SearXNG, telemetry and local inference servers are separate prerequisites for their respective features. Their absence is a feature limitation, not a reason to misreport the entire local API as unhealthy. Conversely, a missing required DB/Redis/storage/mail/selected worker makes startup fail.

## Optional local image inference server

The actual entry point is uvicorn image_server.server:app from backend/ (default example port 7860). It has its own backend/image_server/requirements.txt and needs an explicitly supplied KEEL_IMAGE_MODEL_DIR with legitimate model weights. LOCAL_IMAGE_BASE_URL(S) connects the existing image provider to it. Its /health reports model/device/busy state. This is a separate heavy inference provider, not an implicit core dependency: it is not started without weights/configuration, and no image inference is claimed by worker readiness.
