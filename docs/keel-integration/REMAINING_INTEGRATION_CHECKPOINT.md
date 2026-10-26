# Remaining Node/React integration checkpoint

Base: a00669dd8500dcce7dba9d94e2fbfac5a22d8808. Existing development worktree: %TEMP%/KEEL/billing-e2e-cert-20261025, codex/billing-original-ui-completion. No new branch, venv or container.

## Phase 3 checkpoint ? implemented and scoped verification passed

- Original bilingual catalog form, SKU validation/tenant uniqueness, optimistic product versions and rename aliases. Existing Python product, inventory, quick-sale, discovery, capacity and accounting authorities retained.
- Strict intersecting UUID/SKU/name/barcode resolution; ambiguous/conflicting references cannot silently select a product.
- Durable manual upload identity: same request/file/job/staging/reservation on interrupted retry; completed response replay; deterministic PDF document registration. Legacy sales, knowledge documents and provider sync remain distinct.
- Original structured invoice/inventory templates and review component restored. Preview/review/post uses existing M97 drafts, atomic canonical writes, immutable receipt/audit, concurrency protection, stale-review detection and owner/admin authorization. Zero stock is explicit. Historical invoices do not decrement current stock. Python demand continues counting non-cancelled invoices (including unpaid); no model math changed.
- Four additive migrations 20261106000000 through 20261106000300. Regression disposable database e51defeb369745 has 127 migrations. Runtime ba624f1dc5ba47 has 126 at this checkpoint; 127 must be applied before final runtime alignment. Existing historical migrations unchanged.
- Evidence: %TEMP%/KEEL/RemainingIntegrationRuns/20261026-a00669d. phase3-final: 158 passed, zero failed/skipped; phase3-frontend: 192 passed, zero failed/skipped; lint and production build passed. Earlier overlapping suites are not added to this count. Synthetic JWT length warnings retained.
- Actual Chrome journey PASS: original bilingual product form -> canonical product/SKU -> inventory file preview -> original review -> explicit confirmation -> stock 8 to 5 -> persisted reload -> Arabic mobile RTL. Resource ledger phase3-browser/phase3-browser-resource-ledger.json, product 059fa7f6-0f10-4605-8439-24b124c4a8ad, batch 4dbe48a8-dab1-4c96-bcae-147ff371edbf. No mock API, new account, Stripe or external store operation.

### Exact remaining Phase 3 differences

Multiple source/warehouse balances must not collapse silently into Python's single manual balance: guarded pending safe reconciliation. Original complete catalog archive/restore/GTIN batch screens still require Phase 5 reconciliation. Do not call these complete.

## Phase 4 checkpoint ? safe technical additions verified

Reused secure Shopify/Woo adapters, OAuth/vault, existing fenced worker and receipt/identity/staging authorities. Added POST /onboarding/shopify/webhooks/{source_id}, exact-body HMAC before restricted identity lookup, bound shop identity, 2MB limit, durable digest-only receipt, duplicate/content-conflict handling and audited state. Numeric privacy shop IDs correctly match verified GraphQL GIDs. Uninstall requires its signed shop ID and disables only its source. Privacy jobs retain no payload/customer PII; redact topics atomically hold the source and block reconnect/reimport. They explicitly remain policy_review_required, never falsely report erasure.

Migration128: 20261107000000_shopify_delivery_intake.sql applied only to identified disposable regression DB. Order-only incremental scans reuse existing completed checkpoints/configuration versions: Shopify inclusive provider timestamp, Woo exclusive-second boundary overlap/GMT. Product/variant and inventory full snapshots retained because child changes cannot safely be inferred from parent timestamps. Failed/partial jobs never move watermarks; native failure/retry test proves this. Relevant commerce/security/native group: 98 passed, zero failed/skipped (phase4-final.xml). HTTP signed-provider requests use synthetic cryptographic fixtures and real PostgreSQL; actual merchant sandbox E2E remains UNRUN without approved credentials.

Source-owned order/stock automatic canonical reconciliation is still PARTIAL; typed evidence and review remain the existing authority. Universal source priority/refund/shared invoice collision policy is unresolved. Exact privacy target fields, retention and irreversible erasure are POLICY-BLOCKED; reversible holds are implemented. No external provider credentials, store writes or new worker authority introduced.

Technical filter references: https://shopify.dev/docs/api/admin-graphql/latest/queries/orders and https://woocommerce.github.io/woocommerce-rest-api-docs/ (read 2026-10-26).

## Phase 5 checkpoint ? catalog and feature-history integration verified

Original CatalogPage, CatalogProductPage, CatalogTable, GtinImport, productText and RecordSummary ported from D:/freeup space/New folder/Keel/root/frontend/src. Same original form, cards, tables, confirmation dialogs, CSS and bilingual labels. Compatibility adapters use Python canonical products, usage/capacity and price-history trigger. New /catalog and /catalog/:productId routes preserve main /products list, ProductHub, quick sale and forecast pages; a visible original-catalog link is provided on Products.

GET /catalog/products/detail supports original localized shapes, search, sorting, active/archive paging, capacity and price/inventory history. Versioned archive/restore keeps stock and historical records, checks existing Python capacity and SKU uniqueness, and audits changes. Original strict GTIN CSV/XLSX workflow rejects non-text/formula cells, bad checksums, duplicate/missing SKU, stale versions, oversize/too-many rows; applies atomically through existing update_product with audit. Browser exposed JSON-default multipart failure; adapter fixed and real multipart regression added.

MPI GET /history projects the existing evidence_records authority with subject validation, tenant isolation and pagination. It never scores, calls providers or charges; native tests verify unchanged evidence/accounting counts on repeated reads. Existing summary/scoring/cold-start functions unchanged. Frontend MPI caches now include tenant; history has English/Arabic labels, localized dates and truthful empty/error states. Pricing history already existed and is reused. Optional Idempotency-Key on single-product pricing links response/evidence atomically (migration129, 20261108000000_pricing_request_result_links.sql); concurrent replay writes one recommendation, interrupted evidence write rolls back. Existing rule math, default pipeline commit behavior, legacy callers and batch semantics retained; no new charge/meter or price policy threshold.

Evidence: phase5-final.xml 142 native/API/pipeline tests passed, zero failed/skipped; phase5-frontend-final.log 195 frontend tests passed, lint/build passed. Counts overlap earlier phases and are not summed. Actual Chrome original catalog search -> GTIN preview/apply -> archive -> reload -> restore -> unchanged stock5 -> persisted no-reviews UNKNOWN MPI evidence/history -> Arabic390px RTL passed; no console errors, Stripe or store calls. Evidence phase5-browser/catalog-browser-ledger.json and screenshots/API status log. Synthetic product reused, no new account/product/Checkout.

Runtime8024 currently has128 migrations and dirty Phase5 source at the last reload; align129 and committed revision before final browser readiness claim. Regression DB has129. Phase5 does not claim price age/FX, MPI sample/cap/recency, source priority or privacy erasure decisions are approved. It preserves existing Python models and gates.

## Phase 6 pending

Fresh/upgrade/repeat migrations, affected native/worker/accounting/security/frontend regressions and selected real browser journeys. No repetition of unchanged real Stripe E2E. Verdict is not READY yet.

## Preservation

Integration backend/.env.example SHA256 6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28 must remain unchanged. Original D: Node/React remain read-only. No push/main merge/deployment or protected runtime/database modifications.
