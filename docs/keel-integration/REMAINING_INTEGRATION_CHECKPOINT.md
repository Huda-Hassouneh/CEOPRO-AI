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

## Phase 6 verification checkpoint ? in progress

- Affected credit/operation-receipt, upload/RAG, storage recovery, company data, dashboard/inventory/forecast and pricing regressions:143 passed, zero skipped (phase6-affected.xml).
- Fresh129 installation, original123+6 upgrade and repeat0 verified, restricted password login/FORCE RLS and legacy product/stock preservation passed. New API journeys on that fresh database:33 passed, zero skipped. These are pre-migration130 evidence, not the final schema claim.
- Impact testing reproduced a new pricing receipt FK blocking existing whole-company deletion. Forward migration130 (20261108000100_pricing_receipt_tenant_cleanup.sql) fixes cascade cleanup only when the company is actually deleted; normal direct result deletion stays forbidden. Pricing/company regression7 passed.
- Also reproduced the existing M97 intentional import-audit RESTRICT boundary after newly exposed manual imports. It is not bypassed: company deletion now returns explicit409 INTEGRATION_EVIDENCE_REVIEW_REQUIRED before any write. Existing import/provider immutability and pending retention policy preserved; no erasure policy invented. Complete cleanup group22 passed. Ordinary non-retained company deletion still passes.
- Catalog localized search now reuses existing any_text helper (no false matches on JSON locale keys);10 native catalog tests passed.
- Next: final130 fresh/upgrade/repeat proof, scoped final native/browser alignment, then finish source product posting/review boundary or mark its exact policy/implementation limits. No full-parity verdict yet.

## Outstanding final verification


Fresh/upgrade/repeat migrations, affected native/worker/accounting/security/frontend regressions and selected real browser journeys. No repetition of unchanged real Stripe E2E. Verdict is not READY yet.

## Preservation

Integration backend/.env.example SHA256 6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28 must remain unchanged. Original D: Node/React remain read-only. No push/main merge/deployment or protected runtime/database modifications.

## Source catalog/provider follow-up checkpoint

Original source product review now uses the existing M95 identity, M98 typed review, canonical product/capacity and discovery authorities. Owner-confirmed create/link never overwrites a manually linked price or stock. Latest completed source revision and configuration must still match; source/revision locks serialize owner posting against worker updates. Three forward migrations131-133 add only supported typed product fields and restricted locking guards. Regression DB133; runtime132 at browser verification, final alignment pending.

Woo simple/variation names, SKU, GTIN, currency and prices now remain usable instead of unconditional unsupported findings. Shopify ProductVariant scalar money fields follow the actual provider contract using authenticated shop currency. Fixed valid outer pagination being rejected as duplicate; nested cursor replay is still rejected. Existing secure adapters/worker remain the sole provider authority.

Evidence: phase4-provider-contract-final.xml71 passed; phase4-source-post-final.xml15 passed; phase4-source-guard-final.xml21 passed; phase4-canonical-concurrency.xml6 passed (overlapping groups, never summed). Frontend197 passed, lint/build passed. Actual Chrome source review/confirm -> persisted canonical product/link -> reload -> Arabic mobile RTL passed, errors empty; phase4-browser/provider-browser-ledger.json. Upstream is explicitly CONTROLLED_PROVIDER_FIXTURE_NOT_REAL_STORE, not real merchant acceptance.

Recovered original source-specific invoice namespace SH-/WC- plus source UUID/order ID and reserved inventory location rules. These are established original behavior; only actual authority collisions/unapproved privacy erasure remain policy-dependent. Next: reconcile source orders/stock using those exact rules and existing authorities, then final fresh/123-upgrade/repeat migration verification, affected regressions and safe fast-forward. No new Stripe resources or unchanged billing E2E repeats.

## Source accounting, stock and conditional automation milestone

Recovered original pure order normalizers from read-only original ai/src/ai/connectors, not its HTTP service. Existing pinned/bounded Shopify/Woo clients now collect actual accounting fields/allocated refunds. Strict allowlisted M98 projection excludes customer PII. Owner order preview/confirm posts original source-namespaced invoices and source-owned sales through existing canonical tables/M95 association. Stable line links, bounded four-decimal rounding adjustment, exact shipping/tax/refund totals, provider payment evidence, stale/collision/manual-change holds and atomic receipts/audit. Cancellation removes only source-owned sales; distinct manual sales survive. No stock decrement or subscription/Credit activation.

Explicit stock review reuses M96 source/field/location decisions and existing canonical inventory numeric validation. Current-scan membership handles duplicate observations; unknown/unmanaged/missing stock never becomes zero. Only one explicitly selected quantity/location projects into Python's existing single-balance consumer model. Existing manual/multi-balance/conflicting ownership remains protected; no universal source priority or aggregation is inferred. All physical source/location observations remain evidence.

Owner conditional authorization (2026-10-26): default-off automatic promotion only in disposable environments; explicit Tenant Owner opt-in per source/category; preserve manual review; stock must already have owner-selected source/field/location. Implemented append-only category decisions, strict runtime gate, existing-service reconciliation and staged-record retry. Rollback/retry native proof creates one logical product and no new provider read. Tenant Admin/direct-SQL opt-in denied. Automatic order/invoice category is refused by API AND database pending separate payment/tax/currency/cancellation/deduplication mapping approval. No production automatic posting authorized.

Four forward migrations134-137 (20261110000000 through20261110000300). Final fresh137, original123+14 upgrade, repeat0, restricted-role password/FORCE RLS/immutable receipt privileges, legacy product/stock/paid invoice preserved: phase6-final-migrations/migration-results.json. Initial unapplied135 composite FK error was corrected before successful application; its failed log remains in phase4-order-migrations. Existing applied migration files remain immutable.

phase4-commerce-acceptance.xml:129 passed, zero failed/skipped. Includes real PostgreSQL API, worker, webhook, tenancy, authority, concurrency, accounting and failure recovery tests with controlled provider fixtures; actual merchant E2E UNRUN. Frontend199 passed, lint passed. Earlier overlapping group counts are not summed. Final build/browser/runtime alignment and affected consumer regressions are next. Automatic review initially rejected database tests; replaced unsafe/unidentified targeting with this run's newly created ledger-owned fresh DB and finally-restored synthetic role/invoice fault injections. Automatic worker promotion was separately blocked until the owner's explicit conditional authorization above.

Next exact action: save milestone; apply134-137 to positively identified disposable browser runtime (currently132), reload ONLY recorded8024 after preserving logs; verify original data-connections controls -> real order/stock persistence/audit and source category settings in actual Chrome; run affected main consumers; safe fast-forward integration preserving .env.example.
