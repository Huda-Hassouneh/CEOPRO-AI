# Assistant: speed, social conversation and external research — audit and plan

Status: **plan for approval**, 2026-11-06. No production, database, model or deployment change has been made.

## 1. Audit of the current path (measured locally, synthetic demo company)

`advisor.answer()` runs in this order:

1. **`conversation.classify`.** Greetings, thanks, farewells, "who are you" and introductions get a fixed reply.
   No search and no model call.
2. **Understanding.** Rules first (`understanding.py`). A local model is a second reader only when
   `RAG_LLM_UNDERSTANDING=gaps`, which is off in production.
3. **Company records and documents.** Exact records (`business_records.py`), plus documents through BM25 and
   embeddings.
4. **Public research** (`research/research.py`), only for external needs: market, competitors' public
   information, regulation and trade.
   - Queries are stripped of private figures (`public_safe`).
   - Every source carries its URL, publisher and date.
   - Budgets apply per server and per company.
   - Every outcome is explicit: not set up, budget used, nothing found, or pages unreadable.
5. **One model call** writes the cited answer: `openai/gpt-oss-20b` on Groq. `citations.py` checks it. Without a
   model, evidence mode answers from the records alone.

Latency measured locally without a model (`use_ai=False`):

| Kind of message | Median | Max |
|---|---|---|
| Greetings and thanks | 0.00 s | 0.00 s |
| Simple business question (sales, stock, price) | 0.12 s | 0.65 s |
| Policy or document question | 0.01 s | 0.01 s |

**So nearly all real latency is the model call.** It could not be measured here because the Groq key in this
environment is rejected.

If the local CPU reader is switched on, it adds 7–15 s whenever it is asked (11–22% of questions). It must
stay off for any "under 3 s" target.

Gaps found in social handling (probe of 45 messages):
- **Misread as business questions:** «لو سمحت», «بشوفك بعدين», «شو بتعرف تعمل؟», «الحمدلله», «والله انك رائع».
- **Inconsistent register:** replies switch between formal Arabic and Jordanian; a Jordanian «صباحو» gets a formal
  «بماذا أستطيع».
- **Emoji:** they get an English reply.

Gaps found in external information:
- **No search provider configured here.** `WEB_SEARCH_PROVIDERS` supports Tavily (free tier, no card), Brave
  (card on file), SearXNG (self-hosted) and Google CSE (ends 2027-01-01).
- **No general-knowledge source** (encyclopaedia or official statistics) besides web search.
- **No test set** for research accuracy, source reliability or hallucinations.

## 2. Plan: smallest safe changes, in order

### A. Speed (no model change)

1. **Direct answers for simple single-need questions.** One need, records found, nothing to analyse: today's
   sales, stock of a named product, a product's price, the number of products, a policy passage.
   - The reply is written from the exact records with a fixed bilingual template, citing the same evidence.
   - No model call, so the cost is the 0.1–0.7 s above.
   - Everything else (comparisons, "why", advice, multi-part, external) still goes to the model.
   - Guarded by the existing citation check. Measured against the 121-case SQL-truth regression suite before
     and after.
2. **Keep the local CPU reader off** for interactive answers. The rules gate stays, and the rules alone handle
   greetings and common questions.
3. **Exact repeat cache, per company and per data version.** The same question, unchanged records and the same
   permissions give the stored answer. It is invalidated by any new invoice, stock change, document or price
   change, and by the day changing for relative periods. It is never shared across companies or roles, and
   never used for research answers older than the research cache rules allow.
   Optional; only if step 1 leaves a measurable gap.
4. **Measure the production path with the model.** This needs a working free Groq key, or another approved
   provider, in this environment. Until then, model-path numbers are reported as "not measured".

### B. Natural social conversation

1. Extend `conversation.py`:
   - polite openers alone or before a question («لو سمحت», «من فضلك»);
   - farewells («بشوفك بعدين», «يلا باي», «الله معك»);
   - capability questions («شو بتعرف تعمل؟», «what can you do»);
   - compliments, «الحمدلله», laughter and emoji;
   - "greeting + question" keeps answering the question.
2. **Reply in the user's register:** Jordanian/Levantine to dialect, formal Arabic to formal Arabic, English to
   English, and mixed messages in the main language. Short, warm, never business figures.

### C. Business knowledge and external information

1. **Routing stays "company data first".** Questions about the company's own sales, stock, products, expenses or
   performance use KEEL records only and are never sent out. Research runs only for external needs or when the
   records cannot answer.
2. **Answers keep the two clearly apart:**
   - «من سجلات شركتك» / "From your records" — figures with record citations;
   - «من مصادر عامة (تم الاسترجاع بتاريخ …)» / "From public sources (retrieved …)" — each claim with its link.
3. **Free providers only.** Tavily free tier (1,000 searches a month, no card) as the web search; the proxy
   already has a Tavily credential, to be verified on the API host. Optionally Wikipedia/Wikidata and the
   World Bank open API for general and economic facts (free, no key).
4. **Hallucination guards:**
   - A public claim must quote or paraphrase a passage from a cited page; claims without support are dropped.
   - No figure is written without a source.
   - "Not found" is said plainly.
   - The outgoing query is logged in public-safe form for audit.

## 3. Independent test sets (new; kept apart from all existing sets)

Each set is split into development / validation / sealed final. Only development is used for tuning. Sealed
sets are fingerprinted before any change, and all of them are labelled unreviewed until a native speaker
reviews them.

| Set | Size (dev / val / sealed) | Content |
|---|---|---|
| Social | 80 / 40 / 60 | greetings, thanks, polite openers, farewells, compliments, emoji, "greeting + question"; Jordanian, Levantine, Gulf, Egyptian, formal Arabic, English, mixed |
| Jordanian everyday business | reuse `dev_jo2` / `val_jo2` + a new sealed 60 | as in the Jordanian round |
| Business research | 40 / 20 / 40 | market trends, competitors' public information, demand and seasonality, regulation, prices in Jordan; plus "should be answered from our records" questions that must not trigger research |

## 4. Acceptance criteria (measured on the sealed sets, reported with 95% confidence intervals)

| Area | Criterion |
|---|---|
| Social | ≥ 97% classified as social when social (and as business when business); 0 replies with business figures; register matches ≥ 95%; median < 50 ms |
| Simple business speed | median < 1 s and P95 < 3 s end to end locally with direct answers; production path reported once measurable |
| Accuracy kept | 121-case regression suite stays 121/121; understanding pools no lower than today |
| Routing | ≥ 95% of company-data questions answered without research; ≥ 90% of external questions trigger research |
| Research answers | 100% of public claims carry a working source link and retrieval date; ≤ 2% unsupported claims (manual check of every answer in the sealed set); 0 invented companies, figures or citations; "not found" given when no source |
| Privacy | 0 outgoing queries containing company figures, customer names or invoice data (automated check on every research query) |
| Resources | no new paid service; memory and CPU reported; research stays within the configured budgets |

## 5. Needs approval or input

- **Model-path latency:** a working free Groq key, or another approved provider, to measure the production path.
- **Web search:** use the Tavily free tier (and optionally the Wikipedia/World Bank APIs) for research.
- **Native-speaker review** of the social and Jordanian sets.
- **Order of work:** A1 → B → C, each committed to main only after its tests pass.
