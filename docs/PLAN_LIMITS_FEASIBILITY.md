# Agreed plan limits: feasibility, profitability and enforcement audit

Updated 2026-10-09. Prices and limits below are the owner's agreed terms and
are not changed by this report. Cost model: `backend/scripts/plan_cost_model.py`.

| Limit | Starter $55 | Growth $140 | Enterprise $350 |
|---|---:|---:|---:|
| Products | 250 | 2,000 | 10,000 |
| Tracked competitors | 10 | 30 | 100 |
| Reviews analyzed / month | 5,000 | 25,000 | 100,000 |
| AI tokens / month | 100,000 | 500,000 | 2,000,000 |
| Connected data sources | 1 | 5 | 20 |
| Storage | 1 GB | 10 GB | 50 GB |
| Document uploads / month | 50 MB | 500 MB | 2,048 MB |
| AI marketing images / month | 20 | 100 | 150 |

All plans include market intelligence, demand forecasting, competitor
tracking, price analysis, reviews and sentiment, and AI insights.

Evidence key: **M** measured in this repository; **V** vendor's own page
(seen through search - the sandbox cannot open vendor sites directly);
**S** secondary source only; **A** assumption.

## 1. Verdict

1. **The prices are profitable at the agreed limits with paid usage-based
   providers** - gross margin at full quota 52-75% (monthly) and 35-70%
   (6-month price), see section 4. Nothing needs to change in prices or limits.
2. **The limits can be enforced server-side safely** after closing the gaps in
   section 3; storing them is a non-destructive update.
3. **Strictly free infrastructure cannot reliably deliver the full quotas to
   more than a handful of customers.** The binding limits are the AI model's
   free tier (per-minute tokens), competitor/review data collection, image
   generation, the 10 GB free object storage, the 1 GB free database and
   the 512 MB / 0.1 CPU free web instance (section 2). The quotas are
   ceilings; typical usage is far below them, but a customer who uses a full
   allowance would hit a platform-wide free cap, not their own.

## 2. Can free infrastructure carry each limit?

| Limit | What it costs to serve | Free capacity (whole platform) | Reliable on free? |
|---|---|---|---|
| Products | DB rows only (~1 KB each with prices) | negligible | **Yes** |
| Connected data sources | connector syncs, own CPU | CPU on the one free instance | **Yes** at low volume |
| AI tokens | M: ~2,300 tokens per question (1,550-1,750 prompt + reply); LLM free tier S: ~8,000 tokens/min, ~100-200k/day per account | **~3 questions per minute for all customers together** (M: 429 waits of 38 s at the 5th question) | **No** beyond pilot use. Paid tier: V/S $0.075 in, $0.30 out per 1M - Enterprise's full 2M ≤ $0.60 |
| Competitor refresh | Website price checks: own crawler, no fee. Map listing data: Place Details Enterprise+Atmosphere V $25/1k, **1,000 free calls/month per SKU per billing account** | Weekly refresh: Starter 43, Growth 130, Enterprise 433 calls/month - the free 1,000 covers ~23 Starter or ~7 Growth or ~2 Enterprise | **Partly**: website checks yes; map refresh only for a few customers. Public OpenStreetMap servers forbid commercial heavy use (V) |
| Reviews collected | Customer imports: free. Map details: max 5 reviews per call. Bulk reviews: V $0.50/1k; Apify gives $5 free credit/month (V) | ~10,000 bought reviews/month platform-wide from the free credit | **Partly**: imports yes; bulk collection only for 1-2 customers |
| Reviews analyzed | M: 16 reviews/s per CPU core (8-bit ONNX), 5/s (current torch); model needs 348 MB (8-bit) | Free web instance: 0.1 CPU, 512 MB shared with the API | **No** with the model (memory); **yes** with the labelled star-rating fallback only |
| Storage | V: R2 $0.015/GB-month, **10 GB free per account** | 10 GB for all customers | **No** for one Growth (10 GB) or any Enterprise (50 GB) at full use; cost when paid ≤ $0.75/month |
| Document uploads | M: 10,000-row CSV in 2.4 s, 2,000-row xlsx in 0.7 s (4 cores); free instance is 0.1 CPU | CPU-bound, slow but works | **Yes**, slower |
| Marketing images | Paid FLUX-schnell hosts S: ~$0.003 per 1024² image; free HF credit V: $0.10/month (≈ tens of images) | Not reliable: keyless public endpoint has no service guarantee; generation not verified end to end here (hosts blocked) | **No** - needs a paid image account to promise 20/100/150 |
| Database | M: ~690 B per sale line (+250 B transactions copy, +380 B kept import staging rows); ~440 B per review. Neon free V: 1 GB storage, 100 CU-hours/month per project | The demo company (52,701 sales lines) ≈ 70 MB; Enterprise at 100k reviews/month adds ~44 MB/month | **Yes** for a few companies; not for many at full quotas |
| Background jobs | competitor refresh, sentiment, forecasts | Render: **no free background workers** (V); 750 free instance hours/month for the whole account | Only inside the one free web service, which sleeps after 15 min idle (V) |

## 3. Enforcement audit (code as of commit 1536393)

| Limit | Enforced at | Gaps (customer can exceed the limit) |
|---|---|---|
| Products | `POST /products` (`products.py:526`) | **G1** file imports (`extraction/promotion.py`) and POS/ERP connector syncs create products without checking |
| Tracked competitors | `POST /competitors` add, discovery track, discovery auto-track (capped by plan) | **G2** legacy discovery (`market_scraper/discovery.py`) inserts competitors that are tracked by default without a cap |
| Reviews analyzed | `sentiment/pipeline.py` clamps each batch to what is left, then records | **G6** not reserved atomically: two runs at once can overshoot by up to one batch (100) |
| AI tokens | assistant: reserve 2,500 then settle to the real count (`rag.py`) | **G5** marketing text generation (`marketing/content_generator.py`) calls the model without counting tokens |
| Connected data sources | both connector registrations (`onboarding.py`) | none found |
| Storage | PDFs uploaded for the assistant only (`extraction.py:371`); usage counts `rag_documents_metadata` only | **G3** spreadsheets kept from uploads, marketing images (uploaded and generated) are neither checked nor counted |
| Document uploads / month | `/extraction/upload` reserves KB | **G4** review imports and marketing image uploads are not counted |
| Marketing images | reserve before generating, release on failure (`marketing.py:549`) | none found |
| Modules (all plans) | `entitlements.requires()` per router, `PlanGate` in the UI | today Starter is blocked from market, demand and competitors - must be opened |
| Refresh frequency | - | **G7** no scheduled competitor price refresh exists; area discovery reruns weekly for every plan |
| Monthly reset | counters keyed by the period start (subscription period, else calendar month) - no reset job needed | needs a test that a new period starts at 0 |

### Status after the fixes (commits 368475a and the storage commit after it)

- G1 closed: imports and connector syncs create products only up to the limit and report the rows that didn't fit.
- G2 closed: discovery and classification keep competitors beyond the cap as suggestions.
- G3 closed: storage counts assistant documents plus every stored marketing image and upload result (`tenant_storage_objects`); files stored before this change are not counted.
- G4 closed: review imports and marketing image uploads count toward the monthly upload allowance.
- G5 closed: campaign writing uses the AI token allowance.
- G6 open (minor): review analysis can overshoot by at most one batch of 100 when two runs overlap.
- G7 open: no scheduled competitor refresh yet.

## 4. Cost and margin (unchanged from the first report; inputs re-checked)

Full-quota worst case per company per month: Starter $12.32, Growth $53.66,
Enterprise $161.51 (Enterprise competitors refreshed daily through the official
map API; refreshing every 6 hours would cost ~$386 and lose money). Payment
processing is the largest fixed share (Stripe, international card: 5.1-6.1% +
$0.30). Gross margin after shared hosting:

| Customers, hosting | Starter normal / full | Growth normal / full | Enterprise normal / full |
|---|---|---|---|
| 10, lean ($80/mo) | 75% / 63% | 83% / 56% | 86% / 52% |
| 50, lean | 87% / 75% | 87% / 60% | 88% / 53% |
| 10, robust ($247/mo) | 45% / 33% | 71% / 44% | 81% / 47% |
| 6-month price, 10, robust | 32% / 17% | 65% / 32% | 78% / 35% |

Break-even: with $0 hosting (free tier) every paying customer is profitable;
with lean paid hosting ($80/month) about 2 Starter customers cover it, with
robust hosting ($247) about 5.

## 5. Minimum practical free-tier architecture (for a pilot)

- One Render free web service running the API **and** the light background
  loops (competitor website checks, forecasts, review analysis in small
  batches) - it sleeps when idle, so jobs run when someone uses the app.
- Neon free Postgres (1 GB), Render free Key Value only for cache/rate limits
  (25 MB, not persistent - jobs must be recorded in Postgres), R2 free 10 GB.
- AI: the LLM free tier for a pilot; a usage-based paid tier before more than
  a few active customers.
- Reviews: customer imports plus labelled star-rating sentiment; model-based
  sentiment needs ~350 MB more memory than the free instance has next to the API.
- Images and bulk competitor/review data: off until a paid account is approved.

## 6. Search provider shutdown (verified)

Google's own Custom Search JSON API overview: closed to new customers; existing
customers must move by **1 January 2027** - a discontinuation, not only closed
sign-ups. Radar now searches through a provider-neutral interface
(`market_scraper/web_search.py`): Brave (V: $5 monthly credit, card on file),
Tavily (V: 1,000 free credits/month, no card), self-hosted SearXNG, or Google
for accounts that have it. None is configured or live-tested here.
