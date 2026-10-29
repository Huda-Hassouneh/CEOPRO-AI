# Business assistant: why it couldn't answer company, sales and market questions, and the fix

Date: 2026-10-29. Run locally against the real application (FastAPI backend, Postgres 16 +
pgvector with row-level security, Redis, an S3-compatible store) with two demo companies
seeded through the public API (`scripts/demo_companies`): Zaytouna Fine Foods (JO/JOD,
28 products, 52,973 invoices from 2025-04-01 to 2026-10-28, 245 reviews, 5 PDFs) and ByteFix
Electronics (EG/EGP). Embeddings ran as in production (`RAG_EMBEDDING_BACKEND=static`,
reranker off).

## What was failing, and where

Each failure was traced to the step that lost the answer, by capturing the exact prompt the
model receives (`advisor._prompt`) and comparing it with independent SQL on the same database.
The language model was not the cause. In every case below, the figure asked for never reached it.

| # | Question (examples) | What the assistant got | Root cause |
|---|---|---|---|
| 1 | "How much did we sell in March 2026?", "Compare Q2 2026 with Q2 2025", "كم كانت مبيعاتي في شهر آذار؟", "sales in 2025", "between 1 May and 15 June" | No sales figure for that period at all: the demand-forecast summary instead | `understanding.py` read no calendar periods: no month names, quarters, years, date ranges or "yesterday", in any language. |
| 2 | "What was my revenue last month?", "this month", "this year" | Trailing 30 / 365 days, presented as "last month" / "this year" | `_NAMED_PERIODS` mapped "last month" to 30 rolling days and "this year" to 365. |
| 3 | "How much did we sell…", "how many did we sell last month?" | No sales intent; treated as a follow-up that inherited the previous turn | "sell" was not a sales keyword (only sale/sold/selling). |
| 4 | "What do customers say about us?", "Has customer sentiment improved?" | Classified as a **customs/trade** question (public research, regulatory checks) | Keywords matched as substrings: "custom" ⊂ "customers" (likewise "sale" ⊂ "wholesale", "tax" ⊂ "syntax"). |
| 5 | "How many units of Sidr Honey did we sell…", "and its stock?" | Product sales and stock only if the product happened to be in a top-5 list | No per-product sales, stock or forecast record existed. |
| 6 | "Demand forecast for olive oil", "كم المخزون عندي من زيت الزيتون؟" | Five forecasts in UUID order (effectively random); no olive oil | `structured_context._build_forecast_lines` used `LIMIT 5` inside `DISTINCT ON`; a product had to be named in full ("Extra Virgin Olive Oil 1L") to be recognised. |
| 7 | "Top selling product this year by units" | Revenue ranking only, and the 90-day revenue leader was treated as "the product asked about" | Rankings were by revenue only; the `top_product` slot (meant for "import my top product") hijacked ranking questions. |
| 8 | "Has customer sentiment improved over the last 3 months?" | One overall score; four identical copies of the same review | No positive/negative counts or month-by-month data; review samples not de-duplicated. |
| 9 | "Tell me about my company" | Sales and competitor lines; the Company Profile PDF was rejected | No company intent; the relevance filter needed two shared words and "tell" counted as one. |
| 10 | "Which product sold the most then?", "and the month before?" | The period of the previous turn was lost | Follow-ups carried only rolling `period_days`; "then", "the month before" and "same period last year" weren't understood. |
| 11 | Any sales question | All five PDFs attached as evidence | Document footers ("Last reviewed September 2026") matched on month names and years. |
| 12 | Any question while the model is down (the default when the provider fails, is rate-limited or credits run out) | The 90-day generated summary shown first for "last month"; a follow-up's own record dropped | Evidence-mode ranking used word overlap only. |
| 13 | Staff asking about revenue with the model down | HTTP 502 | No evidence left after permission filtering, so the error was raised instead of saying the role can't see sales. |

## What changed

- **`rag/periods.py` (new)**: exact calendar periods, end-exclusive, in English and Arabic
  (Levantine and Egyptian month names, attached prepositions such as "بآب", Arabic-Indic
  digits), plus relative periods, quarters, years, single days and ranges. It also gives the
  period before each one and the same period a year earlier. Rolling windows ("the last 90
  days") keep their meaning.
- **`rag/understanding.py`**:
  - Latin keywords now match at the start of a word only.
  - Sales vocabulary is added (sell, earned, بيع, باع…), and "customs" replaces "custom".
  - New `company` intent.
  - Partial product names: two consecutive name words, or one distinctive word, with the
    Arabic article removed.
  - Calendar periods are resolved against the company's own date (`business_today`).
  - Follow-ups replace or add periods ("and in August?", "compare with July", "the month
    before", "same period last year", "then"), and keep the product for elliptical questions.
  - A bare period comparison is a sales question.
- **`rag/business_records.py` (new)**: plain tenant-scoped SQL aggregates for the periods and
  products the question names:
  - revenue and invoices (the dashboard definition), against the period before;
  - units and revenue per product, with top products by revenue and by units;
  - gross profit (costs only for roles that may see them);
  - month-by-month series and the largest customers;
  - each named product's sales, stock, reorder level, days of cover (only with the sales
    capability) and latest forecast;
  - review counts (positive/neutral/negative) per period or month;
  - the company profile.

  A period with no records says so, with the dates the records do cover. An incomplete
  comparison period is flagged.
- **`rag/advisor.py`**:
  - Runs the exact records first (`_records`), and drops the generated summaries they
    supersede and those off the question's topic.
  - Adds a prompt line naming the exact dates to answer for.
  - Treats period words, ranking words, request verbs, month names and years as non-topic
    words.
  - Evidence mode ranks the named product, then the period's headline total, then the other
    question records, with one item per need for combined questions.
  - Gives a plain status answer when nothing may be shown, and says why public research
    didn't run.
- **`rag/structured_context.py`**: every product's latest forecast, the largest first (up to 30), with its range.

Tenant isolation is unchanged: every new query filters by `tenant_id` and runs on the
restricted `ceopro_app` connection under row-level security. Role capabilities from
`rag/access.py` gate every record (sales, costs, inventory, forecasts, reviews), and the sales
pace in stock lines is omitted for roles without the sales capability.

## Regression suite

`backend/scripts/assistant_regression.py` asks the running API (sessions, roles and follow-ups
included) and checks each reply against ground truth computed with **independent SQL** on the
same database. A case fails if the expected figure is absent, or a forbidden one is present:
the wrong period's revenue, another company's data, or figures the role may not see.

```bash
cd backend && python -m scripts.assistant_regression --password '<demo password>' \
    --staff-email <a staff member of the demo company> --report out.json
```

Same 31 cases, same data, same checks:

| Code | Passed |
|---|---|
| Before (commit `2c3224e`, served side by side on another port) | **4/31** (both document cases, the Arabic review overview, the English market question) |
| After | **31/31** |

Full backend suite (`src/ai/tests`, live database): the first run also hit HTTP 429 in auth/marketing
tests, because of the API rate-limit counter in this machine's shared Redis. Every file with a failure was
re-run on both trees with Redis flushed, and both show the **same 6 failures**, all environmental:
Hugging Face downloads blocked here (3) and this local database's billing-plan state (3). All assistant
suites pass (463 tests including the live-database ones).

| Category | Cases | What is verified |
|---|---|---|
| Sales and revenue | last month, named month (EN/AR), quarter vs quarter (EN/AR, Arabic digits), month-to-date (mixed language), conversational comparison, "money made" | exact revenue for those dates; the trailing-30-day figure must not appear |
| Products | top by units this year, top by units last month, a named product's units in a month, catalogue size | product and unit counts |
| Follow-ups | month → "the month before" → "which product sold the most then?"; price → "how many did we sell last month?" → "and its stock?" | period and product carried across turns |
| Inventory and forecast | Arabic partial name stock ("زيت الزيتون"), olive oil forecast | stock and forecast per product |
| Sentiment | Arabic overview, "has sentiment improved over 3 months" | review counts; never classified as customs |
| Documents and company | returns policy, delivery fee, "tell me about my company" | facts from the PDFs |
| Combined | product sales last month + price vs competitors | both parts present |
| Missing information | a period before the records start; customer ranking without customer names | says so; nothing invented |
| Market (external) | average olive oil price in Jordan (EN/AR) | research attempted and its status reported; never the company's cost prices |
| Permissions | staff asking revenue; staff asking stock | no revenue or sales pace; stock shown |
| Isolation | ByteFix asking last month's sales (EN/AR) | ByteFix's revenue only, no Zaytouna product or figure |

Unit and live-database tests: `test_rag_periods.py` (52), `test_rag_business_records_integration_db.py`
(9, RLS role), plus the existing assistant suites updated where behaviour intentionally changed
("last quarter" is now the calendar quarter).

## Limitations and what is still needed

- **No language model was available in this environment.** The Groq key provided to it is
  rejected by Groq (401 "Invalid API Key"), so every reply in the regression run is the
  evidence-mode answer. That path is real (production uses it when the provider fails,
  rate-limits or credits run out), and the integration tests verify exactly what the model
  receives. Model-written answers and their citation repair were not exercised live. Re-run the
  suite with a valid `GROQ_API_KEY`: the same checks apply to model-written text.
- **Semantic (cross-language) document search was not available.** The Hugging Face token
  here is also rejected, so retrieval ran keyword-only (BM25). An Arabic question about an
  English-only document can miss it unless it shares words. The company-profile intent adds
  the English search terms for that one case.
- **Public research is not configured** on this server (no Tavily/Brave/SearXNG/Google key).
  Market questions say so explicitly instead of answering. Configure a provider to answer them.
- Gross profit uses each product's **current** cost price; historical cost changes are not stored.
- A product the company doesn't sell (ByteFix asked about "Sidr Honey") gets the company's
  sales without an explicit "that product is not in your catalogue".
- Partial names can include near matches ("olive oil" also matches "Olive Oil Soap"). Each line
  names its product, so the answer can tell them apart.
- Prompt size grew by about 0.3–1.5k tokens for broad questions. The existing compact-prompt
  retry still covers provider size limits.
