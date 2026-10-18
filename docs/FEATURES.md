# Feature and data readiness

> **18 October review update:** the custom competitor bridge and dependent Smart Alerts UI are suspended. The current team competitor source is restored unchanged. Earlier descriptions of active custom tracking below are historical. See [current review instructions](COMPETITOR_REVIEW.md).


Implemented means a source path exists and has an application contract. It does not certify a live provider account, sufficiently fresh tenant data or production deployment. Permissions, plan entitlement and usage capacity apply to each relevant action.

| Capability | Data needed / workflow | Current boundary |
|---|---|---|
| Signup, onboarding, sessions | Verify identity, create/join tenant, establish permission and plan | Node auth/session/RLS implemented; real email sender configuration required |
| Platform management | Authorized platform tenant/membership and permissions | Separate from merchant tenant ownership; neither implies cross-tenant admin access |
| Plans/billing | Stripe catalog, checkout and verified webhook | Node authoritative; test/live bootstraps are deliberate operations |
| Dashboard | Canonical products, paid invoices, sales, inventory, forecasts and review snapshots | Different KPIs use different tables/windows; products alone do not populate every metric |
| Products | Manual/validated import or persistent store catalog | GTIN optional; check digits/normalization do not generate a registered identity |
| File ingestion | Supported uploaded data → extraction/staging → ingestion worker | Reject/partial rows remain visible; upload alone is not canonical completion |
| Persistent stores | Authorized Woo/Shopify catalog and supported orders | Implemented; permissions/capacity/reachable providers required |
| Inventory intelligence | Observed managed stock plus usable demand coverage | Unknown stock differs from zero; full-period forecast claims require full coverage |
| Demand prediction | Recorded product sales with dates/quantities | Independent of competitor tracking; target-day prediction is not a seven-day total |
| Competitor management | Discover candidates → confirm identity → review source → monitor | No guarantee of a match or crawl permission; discovery alone does not collect prices |
| Market/pricing | Confirmed tracked comparable prices with currency/freshness/provenance | Unusable result is Unavailable; no price mutation or credit consumption for unusable recommendation |
| Review sentiment / MPI | Actual review text, sentiment processing and sufficient sample | Not derived from product names or sales; optional place discovery is not an imported review feed |
| Document storage/extraction | Valid supported files, tenant quota, extraction completion | Binary storage units; RAG 2 MiB upload guard differs from other ingestion limits |
| RAG Assistant | Extracted/indexed authorized documents and reachable provider | Search ranks across indexed content before bounded provider context; citations and unknown answers matter |
| Business recommendations | Recorded sales and validated forecast/market/review evidence | Local insights API; freshness/coverage controls; correlations are not proven causation |
| Smart Alerts | Supported rules and sufficiently fresh valid observations | Durable events/preferences; tenant/platform notification delivery needs respective workers |
| Notifications | Important events plus recipient role, permissions/preferences | Tenant owners receive tenant-authorized events; platform events require platform authorization |
| Exports | Existing page export actions and visible authorized data | Does not repair missing source data or certify an observation |
| Marketing/image generation | Python modules exist | Not a completed canonical frontend workflow; avoid promising generated campaigns in current UI |
| Google Places | Optional provider configuration in Python discovery | Business candidates, not a complete social-review persistent source |
| POS/ERP/database connectors | Some legacy standalone adapters/staging code | Not a completed Node-owned persistent source flow like Woo/Shopify |
| PayPal / other future connectors | Historical/commented references | Not an active alternative billing or storefront integration |

A practical merchant journey is: sign up and choose an entitled plan; connect a store; validate catalog/stock; complete and sync genuine test orders; inspect invoices/sales; forecast products with history; review competitor matches and authorize collection; generate comparable-price recommendations; analyze actual reviews; upload business documents and test RAG; configure alerts/preferences and run notification delivery. Missing evidence should produce an honest empty/unavailable state, not seeded output presented as a live result.

Raw source retention, access authorization, cancellation and audit provenance remain part of these flows. Prefer supported source operations and migrations over editing records directly. Review the original archived test/acceptance notes through version history if reproducing an old scenario; current authoritative setup is in Development and Workers.
