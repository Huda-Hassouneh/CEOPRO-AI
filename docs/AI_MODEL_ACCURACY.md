# AI model accuracy: business assistant (RAG), image generation and demand forecasting

Date: 2026-11-05. Measured on a disposable local stack (Postgres 16 + pgvector with FORCE RLS, Redis, an
S3 stand-in) with the synthetic demo companies from `backend/scripts/demo_companies` (Zaytouna Fine Foods
and ByteFix Electronics seeded through the public API; all seven used for forecasting). No customer data was
used.

Goal: at least 95% accuracy, starting with the assistant, then forecasting. Summary:

| Model | Measure | Before | After | 95% reached? |
|---|---|---|---|---|
| Assistant | Regression suite against the live API (SQL ground truth) | 69/74* | **121/121 (100%)** | Yes, on the tested wordings |
| Assistant | Live API, first run of a held-out set (wordings never tuned against) | 18/25 (72%) on held-out set 1 | 17/20 (85%) on held-out set 2 | **No**: about 85% on new wordings |
| Assistant | Question understanding, offline benchmark, held-out set (65 wordings) | 55/65 (84.6%) | **59/65 (90.8%)** on its one first run | **No**: about 91% on new wordings |
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

## Marketing image generation

Requested: at most 10 seconds per image, more than 10 models, no unacceptable pictures, correct words in the
picture when needed, and when the best model reaches its limit, the next image goes to another model.

What changed (`backend/src/ai/marketing/image_generation.py`):

| Requirement | Implementation |
|---|---|
| More than 10 models | `MODEL_CATALOG`: 14 hosted models (Gemini 2.5 Flash Image and 2.0 Flash image; FLUX.1 [schnell] on Together free and paid, Cloudflare and Hugging Face; Cloudflare Leonardo Lucid Origin and Phoenix, SDXL, SDXL Lightning, DreamShaper 8 LCM; Hugging Face SDXL; Pollinations flux and turbo), plus self-hosted servers and AI Horde. Each provider's list can be overridden (`*_IMAGE_MODELS`). |
| Best first, then the next when one hits its limit | Every account × model is a candidate, tried in quality-rank order. Equal ranks keep the existing account rotation. A rate limit or used-up allowance puts that model (or the whole account, for shared allowances such as Cloudflare's) in a Redis cooldown for its Retry-After, so the next image skips it without a call. |
| 10 seconds maximum | `MARKETING_IMAGE_TOTAL_SECONDS` defaults to 10. Every HTTP call is cut to the time left, and no attempt starts after the deadline. AI Horde (30 s to minutes) is skipped within that budget. A deployment with only a self-hosted server keeps that server's limit: a CPU server needs about 140 s per image. |
| No unacceptable pictures | `quality_problems()` rejects images that are almost black (a provider's safety-filter frame), almost white, flat or one colour, or without visible detail. The next model is tried within the time left. Thresholds are loose: every designed-poster style, minimal and dark ones included, passes (tested). |
| Words in the picture | The optional `text` on `POST /marketing/campaigns/{id}/generate-image`, and a "Words in the picture" field in the Studio. The model is told to leave space and draw no letters. The words are then written on with a real font (`designed_poster.overlay_headline`): exact spelling, Arabic joined and right to left. The designed fallback poster uses the same words as its headline. |

Tests: `test_marketing_image_quality.py` (20 new) and the updated `test_marketing_image_generation.py`; all
226 marketing tests pass, including the live-DB gallery, jobs and lifecycle suites.

### Not verified here: what still needs checking with real keys

- **Speed and picture quality were not measured.** This environment has no keys for any image provider, and
  its network blocks Pollinations, AI Horde, Cloudflare and Together. All tests use simulated providers.
  Whether a real image arrives within 10 s depends on the provider: FLUX.1 [schnell] and SDXL Lightning are
  built to answer in a few seconds, and Gemini usually does. Measure with real keys before relying on it.
- **The new model IDs need a live call.** Cloudflare Lucid Origin / Phoenix, Gemini 2.0 Flash image and
  Together's paid FLUX are taken from the providers' public catalogues and were not called. A wrong or
  retired ID fails fast and the next model is used, but it should be confirmed or removed.
- **The quality gate catches broken images, not ugly ones.** Judging whether a picture matches the prompt,
  or has a deformed product, needs a vision model (for example CLIP or a multimodal LLM). None could be
  downloaded here.
- **Queued batches carry no words yet.** The Studio sends images with words through the direct path. Words
  in queued batches need a column on `image_generation_jobs` (a migration).

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

About a minute on 4 cores (`--workers`; each worker's XGBoost runs on one thread). The 2026-11-05 re-run
reproduced the figures below exactly.

### Results (1 − WAPE on 30-day totals)

| Segment (avg units/day over the prior 90 days) | Forecasts | Accuracy | Oracle ceiling |
|---|---|---|---|
| All products | 588 | **90.9%** | 94.5% |
| Fast (≥ 5/day) | 193 | 91.2% | 94.7% |
| Medium (1–5/day) | 212 | 84.3% | 90.3% |
| Slow (< 1/day) | 183 | 54.9% | 68.7% |
| Company totals (all products summed) | 42 | 92.3% | 96.7% |

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
