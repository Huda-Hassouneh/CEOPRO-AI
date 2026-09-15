# Dashboard source audit

Sources: `doc/ceopro_ai_model_output_schemas.pdf` (pages 3, 5, 8) and the products, inventory, invoices, invoice_items, global_competitors and tenant_competitors definitions in `doc/CEOPRO_Schema.sql`.

| Existing element | Classification and disposition |
| --- | --- |
| Revenue, sales, growth | C: sum non-cancelled invoice totals in the selected currency/period; sum corresponding item quantities; revenue percentage change against the immediately preceding equal period. No prior revenue means unavailable. |
| Inventory | B/C: current tenant inventory records; low when stock_quantity <= reorder_level. Counts records, not a fabricated inventory health percentage. |
| Competitors tracked | B/C: count tenant_competitors with is_tracked=true. |
| Sentiment | A: replace unsupported 72-point score and trend with sentiment_score (-1 to 1), label_counts and sample_size.status. UNKNOWN shows no result; low shows limited reliability. |
| RAG query count and response time | Removed: no verified Dashboard data source. |
| AI insight feed, generic recommendation, top alert reasoning | Removed: no matching AI output contract. |
| Demand change, demand spike, regional opportunity | Removed: unsupported claims and projections. |
| Next-week line forecast | A: replace with one product/date forecast using expected_demand and lower/upper 80% confidence range. No fabricated aggregate confidence interval. |
| Market activity descriptions and competitor changes | Removed: no underlying observations. Replaced by compact nullable composite scores (A, PDF page 8). Missing factors remain missing. |
| Recent activity table | Removed: hardcoded entries not linked to actual database events. |
| Date filter | D: now updates C metrics and sales aggregation. Current snapshots and latest model results explicitly labelled separately. |
| Export, New Query, View All, chart selectors | Removed: inactive controls. |
| Quick Sale | Removed: no implemented workflow. |
| Add Data | Removed from dashboard: onboarding route redirects completed accounts, so not a dependable dashboard action. |
| Ask AI, View Forecast | D: existing /ai-advisor and /demand routes. |
| Layout, locale formatting, navigation | D: existing shell, sidebar, tokens, card and i18n system. |

Added summary: total active tenant products (B/C) and product-scoped price competitiveness (A, 1–10 or null, PDF page 8). System low-stock alerts (C) show only observed stock and reorder threshold. No pricing recommendation or raw_suggested_price is displayed.

Preview fixtures are centralized in dashboardPreviewData.js. Database records are field projections, with numeric values and UUID identifiers. AI objects retain their documented response/row shapes. UI metadata is separate. The deterministic preview adapter is executable, not a new claimed API contract. A future backend must enforce tenant isolation and supply complete scoped records or implement the same aggregation server-side. Invoices are kept in one currency; no implicit currency conversion occurs. Date buckets use UTC, with an inclusive as-of day and exclusive upper boundary. Inventory and model outputs do not claim to follow the revenue period filter.

Only dashboard components/styles/data and dashboard translation keys are intentionally changed. Existing sidebar, topbar, routing and unrelated feature pages remain intact.

Dashboard-specific shell correction: Sidebar.jsx filters the existing Reports item only on /dashboard; all other routes keep their original navigation. Dashboard.css fixes the existing RTL mobile drawer anchoring only when .dashboard-page is present, fills the available shell width, and preserves independent scrolling at every tested width.

Validation before the final build: deterministic aggregation regression checks; /dashboard in EN and AR at 1440, 1024, 768, 390 and 320 px; functional period selection; untranslated-key and horizontal overflow checks; fixed-sidebar/independent-scroll checks; mobile menu open/Escape close; visual inspection of desktop, tablet and Arabic mobile screenshots.
