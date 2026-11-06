# AI model accuracy: business assistant (RAG) and demand forecasting

Date: 2026-11-05. Measured on a disposable local stack (Postgres 16 + pgvector with FORCE RLS, Redis, an
S3 stand-in) with the synthetic demo companies from `backend/scripts/demo_companies` (Zaytouna Fine Foods
and ByteFix Electronics seeded through the public API; all seven used for forecasting). No customer data was
used.

Goal: at least 95% accuracy, starting with the assistant, then forecasting. Summary:

| Model | Measure | Before | After | 95% reached? |
|---|---|---|---|---|
| Assistant | 121-case regression suite (SQL ground truth) | 97 of 121 would have passed* | **121/121 (100%)** | Yes, on the tested wordings |
| Assistant | First run of a held-out set (wordings never tuned against) | 18/25 (72%) on held-out set 1 | 17/20 (85%) on held-out set 2 | **No**: about 85% on new wordings |
| Forecasting | 30-day totals, volume-weighted (1 − WAPE), 588 backtests | 90.9% | 90.9% (unchanged) | **No**: the ceiling on this data is 94.5% |

\* Core 28/29 plus extended 41/45, measured before the fixes; the held-out sets did not exist yet.

Be careful with the first row. Every case that failed was then fixed, so 121/121 means "everything we
tested now works". The held-out rows are the honest estimate for questions nobody tested.

## Assistant (RAG)

### How it is measured

`backend/scripts/assistant_regression.py` sends each question to the running `/rag/query` endpoint, with
sessions, roles and follow-ups. It then checks the reply against ground truth computed with **independent
SQL** on the same database. A case fails if the expected figure is missing, or if a forbidden figure appears
(another period, another company, or a figure the role may not see). It now has four case sets
(`--suite core|extended|holdout|holdout2|all`):

| Set | Cases | Purpose |
|---|---|---|
| core | 31 | The original cases (2026-10-29). |
| extended | 45 | Paraphrases: other period wordings, dialects (Levantine, Egyptian, Gulf, MSA), units, follow-ups, isolation. |
| holdout | 25 | New wordings, scored once before any fix. |
| holdout2 | 20 | A second fresh set, written after the fixes holdout led to, and scored once. |

### Root causes found and fixed

All of them were in question understanding and evidence ranking. None was in the language model.

| Question (example) | What went wrong | Fix |
|---|---|---|
| "How much Za'atar do we have **left**?", "are we **running low** on…", "units **available**", "كم **باقي** عندنا", "الكمية **المتوفرة**" | Not recognised as a stock question | More inventory cues (`understanding.py`) |
| "**Projected** sales … **coming month**" | Not recognised as a forecast question | More forecast cues |
| "**بكم** نبيع السماق؟", "what do we **sell** tahini **for**?" | "sell" was read as a sales-volume question, so the price line was crowded out | Price-ask phrasing is pricing only, unless volume or revenue words appear. The named product's price record ranks first for price questions (`advisor.py`). |
| "**first half** of 2026", "H1", "النصف الأول" | No half-year periods | Half-years and the half before them (`periods.py`) |
| "sales **06/2026**" | Numeric month/year not read | Read as that month |
| "كم بعنا **في آب**؟" | "آب" (August, also "father") needed an English cue word such as "in" | Arabic cues: في، خلال، منذ، من، بشهر |
| "**مبيعات تموز**" (2 words, 11 characters) | Treated as small talk, then HTTP 502 when the model was down | A short message that names a business need is a question |
| "Can customers **return** labneh?" | The relevance filter didn't stem words: "return" vs "returned", "customers" vs "customer" | Same light stemming as the keyword index, plus "-ed" |
| "هل يمكن استرجاع اللبنة؟" against an English-only policy PDF | Keyword search can't cross languages (no embedding model here) | Arabic questions also search with the English catalogue names of the products they name, and English equivalents of policy words |
| Any record whose text repeats its title | Shown as "Sales for May (…): Sales for May (…): no sales" | Evidence mode drops the repeated title |

Unit tests for each fix are in `test_rag_understanding.py`, `test_rag_periods.py` and `test_rag_advisor.py`.

### Verification

- Regression suite, all sets: **121/121** (`--suite all`, with a staff member for the permission cases).
- Assistant and related unit/live-DB tests: 625 passed, 19 skipped, 5 failed. The 5 failures are
  environmental: the Hugging Face and torch packages aren't installed here. The same 5 fail on the unmodified
  code.
- Tenant isolation and role checks are unchanged and still pass (ByteFix cases in EN/AR, staff can't see
  revenue).

### Question understanding: offline benchmark (second round)

`backend/src/ai/rag/eval/understanding_benchmark.py` scores the reading of the question alone: intent,
calendar period (exact start and end dates), product, and whether a ranking is asked. It needs no database
or model and runs in about a second, so it can be used while changing the rules. A unit test
(`test_rag_understanding_benchmark.py`) keeps every case passing in CI.

Its two sets were written together, before any fix: **DEV** (113 wordings) for development, and
**HOLDOUT** (65 wordings) scored only once, at the end.

| Set | Before this round | After |
|---|---|---|
| DEV | 101/113 (89.4%) | 113/113 (100%) |
| HOLDOUT, first run | 55/65 (84.6%) | **59/65 (90.8%)** |

The six holdout misses were then fixed too, so HOLDOUT is now 65/65 but **spent**. Its first-run 90.8% is
the honest estimate; add new wordings before using it again.

Fixed in this round:
- "since June" / "منذ حزيران" (June to today, not June only); "من بداية السنة" / "since the start of the year".
- Levantine/Egyptian "التاني"/"التالت" for second/third (quarters, halves).
- Stock: Egyptian "فاضل", "do we have X" / "فيه عندنا X", "كم X عندنا", reorder ("لازم نطلب").
- Price: "How much is the X?", "كم حق X", "what's X selling for?", "cost the customer".
- Profit: "losing money", "خسرانين"; revenue: "made the most money", "بيجيب فلوس".
- Reviews: "happy with", "بيقولوا ايه عننا"; delivery and fee questions to policy documents; Egyptian "أكتر"
  in rankings.
- English greetings ("good morning") are small talk.
- Arabic fee words (رسوم، أجرة، تكلفة) also search English documents as "fee, price, charge". This fixed a
  regression the live suite caught: "كم رسوم التوصيل للزرقاء؟".

Live API suite after this round: 121/121 (see Verification).

### Question understanding: third round (rules + local model as a second reader)

`rag/llm_understanding.py` adds a local language model as a second reader behind the rules. It is off
unless `RAG_LLM_UNDERSTANDING=gaps`. The model is asked only when the rules are unsure: no need found,
only a generic product need, more than one need, a time word with no period read, or a price question
with no product. It may only fill what the rules left empty (or trim a need the rules added from a word
used in another sense). It can name only catalogue products, and its periods become dates through
`periods.py`. A failed or invalid reply leaves the rules' reading unchanged. No answer caching was added.

**Model comparison** (same prompt, same development questions, 4-CPU / 16 GB machine, llama.cpp,
Q4_K_M unless noted). "Alone" = model without rules, the fair comparison. "With examples" = 18 worked
examples written from development questions only.

| Model | Alone (140 q) | Jordanian alone (18) | Median | P95 | Peak memory | Invalid replies |
|---|---|---|---|---|---|---|
| Qwen3-4B-Instruct-2507, with examples | 85.7% | 11/18 | 12.9 s | 15.4 s | 5.75 GB | 0 |
| Qwen3-1.7B, with examples | 73.6% | 9/18 | 6.9 s | 24.2 s | 2.8 GB | 0 |
| Llama 3.2 3B, with examples | 72.1% | 10/18 | 14.8 s | 30.4 s | 4.7 GB | 0 |
| Llama 3.1 8B, with examples | 87.9% | 16/18 | 18.0 s | 20.7 s | 9.8 GB | 0 |
| gpt-oss-20b MXFP4 (35-question subset) | 42.9% | 1/6 | 30.6 s | 168.9 s | ~13.4 GB | 10/35 |

The production model is still `openai/gpt-oss-20b` on Groq; it was not changed. Its local CPU result
says nothing about Groq, which could not be tested (key rejected). Llama 3.1 8B was KEEL's Groq model
until 2026-09-03; it is not in the current pipeline. Qwen3-4B was frozen for the final test: close to
Llama 3.1 8B in accuracy at about 60% of the memory and steadier latency.

**Final evaluation, scored once, aggregate only** (configuration and both sets fingerprinted first):

| Set | Result | 95% CI |
|---|---|---|
| Sealed v3 (136 q, all dialects) | **132/136 = 97.1%** | 92.7–98.9 |
| — Jordanian / Levantine / mixed | 16/16, 30/30, 10/10 | |
| — Egyptian / English / Gulf / MSA | 28/29, 18/19, 15/16, 15/16 | |
| Sealed Jordanian (87 q, everyday speech) | **73/87 = 83.9%** | 74.8–90.2 |
| — colloquial (slang, typos, idioms) | 26/36 = 72.2% | 56.0–84.2 |
| — simple / compound / mixed English | 33/37, 6/6, 8/8 | |
| — weakest areas | debts 1/4, inventory 7/11, profit 6/8 | |

Latency: questions answered by the rules alone take about 3 ms; the model was asked on 29/136 (v3)
and 34/87 (Jordanian) questions, with P95 about 15 s and max 36 s for those. So the 3-second target is
met only for questions the rules handle. Zero invalid model replies; peak memory 5.76 GB.

**Verdict: not complete.** Sealed v3 passes the 95% minimum but not the 98% stretch. Everyday Jordanian
speech fails at 83.9%, mostly on intent (21 of 23 field errors). Both sets have now been used, so they
cannot guide further tuning. The next round needs a new Jordanian development set, ideally written or
reviewed by native speakers, and a new sealed set. Debt questions also need receivables data: KEEL has no
receivables records for the assistant yet. Answer correctness, faithfulness and citation accuracy with a
model writing the answer were not measured in this round.

### Question understanding: Jordanian round (2026-11-06)

**Order of work, for independence.** A new Jordanian final set (91 questions, `sealed_jo2`) and a validation set
(60, `val_jo2`) were written and fingerprinted first. After that came the per-question diagnosis of the spent
Jordanian final set and a new development set (119, `dev_jo2`, fresh wordings). Rules, prompt meanings and
examples were changed from the development set only. All three sets are author-written by the developer (an AI)
and **not reviewed by a native Jordanian speaker**, so no result below establishes the 95% target.

**Diagnosis of the 21 intent errors** (12 questions in the spent Jordanian final set):

| Category | Errors | Root cause |
|---|---|---|
| Rules sure but wrong, model never asked | 6 | «الطلبيات» (orders) read as demand «الطلب»; «صافي» (net) and «مشتكي» (complaining) unknown |
| Rules found nothing; model misread Jordanian | 11 | «فش عنا», «نواقص», «نجيب جديد» (stock); «عليهم مصاري», «الديون» (debts: no rule, no prompt meaning); «رح يطلب عليه» (demand) |
| Merging rules and model | 4 | «شروط البيع» read as sales; «انخلصت» (paid off) read as stock running out; competitors vs market research |

About 3 of the 21 depend on labelling conventions (debts → sales because invoices hold payment status;
competitors vs market research) that a native reviewer or product owner should confirm.

**Changes.**
- New rule cues for debts and payments (read from invoices), orders, Jordanian stock words, net profit and
  expenses, and complaints.
- «تبعنا» ("our") no longer reads as «بعنا» ("we sold"), and «أسابيع» ("weeks") no longer as «بيع».
- Terms-of-sale questions go to policies, and «delivery … cost» is the delivery-fee policy.
- Months spelled as numbers («شهر عشرة») are read.
- The model may no longer trim a need from a question that joins two needs itself.
- Greetings never call the model.
- Six worked examples from the development set were added. No receivables data, schema or production model change.

**Results** (rules + local Qwen3-4B, model asked only when the rules are unsure; 4-CPU / 16 GB):

| Pool | Before | After | 95% CI |
|---|---|---|---|
| Jordanian development (119) | 68.9% | 114/119 = 95.8% | 90.5–98.2 |
| Jordanian validation (60) | — | 57/60 = 95.0% (second pass) | 86.3–98.3 |
| Earlier development pools (90 / 149 / 140) | 100 / 100 / 100% | 100 / 100 / 100% | |

- **Validation is a second-pass figure.** The first pass was 53/60 = 88.3%. Five of its seven errors were the
  compound-question trimming flaw, which the development set also showed. It was fixed after validation was
  scored, so 95.0% is not an untouched result.
- **Remaining errors:**
  - Typos («امبارخ», «الربخ», «بعنااليوم»).
  - A short product name («الدبس»).
  - Capacity and reorder questions phrased with «طلبية».
  - Market comparison read as market research, not competitors.
- **Latency:** rules-only questions take about 3 ms, and the model is asked on 11–22% of questions. When asked it
  takes 7–15 s (median), with P95 overall about 15 s and max 48 s. Peak memory is 5.8 GB, with zero invalid model
  replies.

**Final result, Jordanian set 2** (scored once with approval on 2026-11-06, aggregate only, fingerprint
`3a77bc40…` unchanged before and after): **84/91 = 92.3%, 95% CI 85.0–96.2.**

- **Below the 95% minimum.** The set is also unreviewed by a native speaker.
- **By kind of question:**
  - simple 30/32, colloquial 28/30, compound 10/11, ambiguous 4/6
  - typos 8/8, mixed English 4/4
- **By business area:**
  - debts 14/14, sales 16/16, inventory 16/17
  - profit 13/15, multi-part 10/12, customers/reviews 0/2
- **The 7 failing questions:** 5 missed a need (intent recall), 3 added an extra need (intent precision), and 1
  missed the product.
- **Speed and reliability:** the model was asked on 24/91 questions, with no invalid replies. Rules-only questions
  take about 3 ms; P95 15.7 s, max 17.7 s. Peak memory 5.8 GB.

### Limits: why this is not "95% everywhere"

- **New wordings: about 85%.** Question understanding is rule-based (keywords, periods, product names).
  Each held-out set exposed new phrasings it didn't know (72%, then 85%). Getting above 95% on unseen
  wordings needs a learned step, not more keyword lists. Two options: let the language model classify
  intent, period and product into the same slots, with the rules as a fallback; or use the multilingual
  embedding model for intent matching.
- **No language model was available.** The Groq key given to this environment is rejected by Groq
  (`invalid_api_key`), so every reply here was the evidence-mode answer. The checks are identical for
  model-written answers, but those weren't exercised. Re-run with a valid `GROQ_API_KEY`:
  `python -m scripts.assistant_regression --suite all ...`.
- **No embedding model.** The Hugging Face token is also rejected, so document search was keyword-only.
  The Arabic-to-English search terms cover common policy words and catalogue names only.
- The suite covers two demo companies. Questions outside its categories (marketing, landed cost, public
  research quality) aren't scored here.

## Demand forecasting

### How it is measured

`backend/scripts/forecast_accuracy_benchmark.py` (new; no database or network needed) runs the production
model selection (`pipeline.choose_forecast`, with outlier capping and the cold-start check) at six past
origins, a month apart, for every product of all seven demo companies: 588 forecasts. It compares each
**30-day total** (the figure screens, restock advice and the assistant use) with actual sales.

Because the generator knows each product's true expected demand, the benchmark also reports an **oracle**:
the accuracy of forecasting the exact true mean. The gap between the oracle and actual sales is randomness
that no model can remove.

```bash
cd backend && python -m scripts.forecast_accuracy_benchmark --origins 6 --report out.json
```

### Results (1 − WAPE on 30-day totals)

| Segment (avg units/day over the prior 90 days) | Forecasts | Accuracy | Oracle ceiling |
|---|---|---|---|
| All products | 588 | **90.9%** | 94.5% |
| Fast (≥ 5/day) | 193 | 91.2% | 94.7% |
| Medium (1–5/day) | 212 | 84.3% | 90.3% |
| Slow (< 1/day) | 183 | 54.9% | 68.7% |
| Company totals (all products summed) | 42 | 92.3% | — |

The current model gets 96% of the way to the ceiling (90.9 / 94.5). **95% is not reachable on this data at
product level**: even a perfect knowledge of true demand scores 94.5%, and much lower for slow sellers.
Median per-product accuracy is 86.5%.

### What was tried and not shipped

Most of the error comes from seasonal turning points. Forecasts made on 1 May (just after Ramadan and Eid
al-Fitr) were 13% too high, and those made on 31 May (summer ahead) were 11% too low. The current baseline
only looks at the last 30–60 days. Each attempt below was backtested on the same 588 forecasts:

| Attempt | Accuracy | Why it didn't help |
|---|---|---|
| Per-product year-over-year seasonal index | 86.9–87.0% | Fixes the bias, but one product's year-ago month is too noisy |
| Company-pooled seasonal index | 89.2% | Products in one company move in opposite directions (summer lifts some, lowers others) |
| Leave Ramadan/Eid days out of the base rate | 90.1% | Helps after Ramadan, hurts elsewhere |
| Pooled index on non-holiday days, plus last occurrence's holiday uplift | 88.9–90.7% | Eid al-Adha moved from 6 June 2025 to 27 May 2026, so year-ago windows misalign |

None beat the current method, so nothing was changed. Tuning further would mostly fit the demo
generator's own assumptions rather than real customers. XGBoost, chosen for 41 of the 588 forecasts, did
better than the baseline on those same cases (87.6% vs 84.4%), so model selection is working as intended.

### What would raise forecast accuracy

- **Real customer history over two or more years.** A seasonal index only becomes reliable once each season
  has been seen more than once.
- **A Hijri-calendar holiday feature.** This needs 2+ occurrences of Ramadan and each Eid in the history.
  The demo data has one Ramadan.
- **Report accuracy at the level decisions are made.** Category or company totals are more accurate than
  single slow-moving SKUs. For slow sellers, the right output is a range or a reorder point, not a point
  estimate.
