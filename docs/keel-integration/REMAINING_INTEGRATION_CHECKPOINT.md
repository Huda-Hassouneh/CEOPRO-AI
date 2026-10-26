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

## Next exact action ? Phase 4

Reuse existing secure Shopify/Woo adapters, OAuth/vault, fenced receipt worker, identity and stock/business staging. Wire the missing public signed webhook receiver to restricted durable receipts; implement privacy restriction/reimport protection without inventing legal erasure fields/retention. Inspect safe incremental checkpoint semantics and canonical promotion boundaries. Actual merchant sandbox E2E remains UNRUN without approved credentials.

## Phase 5 pending

Complete remaining approved catalog controls and pricing/MPI request/history integration boundaries. Preserve existing algorithms, workers and frontend design. PRICE age/FX/newest-invalid thresholds, MPI sample/recency thresholds, universal source priority and exact privacy erasure policy remain unresolved: do not invent them. Business Recommendations remains explicitly deferred per prior ledger.

## Phase 6 pending

Fresh/upgrade/repeat migrations, affected native/worker/accounting/security/frontend regressions and selected real browser journeys. No repetition of unchanged real Stripe E2E. Verdict is not READY yet.

## Preservation

Integration backend/.env.example SHA256 6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28 must remain unchanged. Original D: Node/React remain read-only. No push/main merge/deployment or protected runtime/database modifications.
