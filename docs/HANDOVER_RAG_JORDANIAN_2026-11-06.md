# Handover: assistant understanding and Jordanian dialect work (2026-11-05/06)

Scope: KEEL assistant (RAG) question understanding, local-model comparison and the Jordanian dialect round. All
evaluation was local, on synthetic demo data and a disposable local Postgres. No production model, database,
schema or deployment setting was changed by this work. Details and tables: `docs/AI_MODEL_ACCURACY.md`.

## Commits on main (author and committer Huda Hassouneh)

| Commit | Content |
|---|---|
| `6c9f481` | Assistant accuracy measurement; forecast accuracy benchmark |
| `a5b95f6` | Offline understanding benchmark; broader question reading |
| `7962305` | Hybrid question reading (`rag/llm_understanding.py`, off unless `RAG_LLM_UNDERSTANDING=gaps`); Jordanian round |
| `fc99ae1` | Jordanian final set 2 result (aggregate only) |
| this commit | This handover, the assistant speed/social/research plan, and the evaluation harness |

## Results

| Measure | Result |
|---|---|
| Model comparison, understanding alone (140 dev questions, CPU) | Qwen3-4B with examples 85.7%; Llama 3.1 8B 87.9% (9.8 GB); Qwen3-1.7B 73.6%; Llama 3.2 3B 72.1%; gpt-oss-20b local 42.9% (35-question subset) |
| Sealed v3, all dialects (136, scored once) | 132/136 = 97.1% (CI 92.7–98.9) |
| Sealed Jordanian set 1 (87, scored once) | 73/87 = 83.9% (CI 74.8–90.2); diagnosed afterwards, now spent |
| Jordanian development (119) | 68.9% → 95.8% (CI 90.5–98.2) |
| Jordanian validation (60) | 95.0% (CI 86.3–98.3), second pass; first pass 88.3% |
| Earlier development pools (90 / 149 / 140) | 100% / 100% / 100% |
| **Sealed Jordanian set 2 (91, scored once, final)** | **84/91 = 92.3% (CI 85.0–96.2)**: below the 95% minimum |
| Latency (rules + local Qwen3-4B) | about 3 ms when the rules alone answer; the model is asked on 11–26% of questions, 7–15 s median each on 4 CPUs; peak 5.8 GB; 0 invalid replies |
| Tests | RAG tests 251 passed. Full backend suite: same failures as main before these commits (missing `torch`/`huggingface_hub` locally, local-DB integration tests). |

## Sealed sets and fingerprints (sha256)

| Set | Fingerprint | State |
|---|---|---|
| `sealed_set_v3.py` (136) | `e7e76266…f65944c88` | scored once (2026-11-06) |
| `sealed_jo.py` (87) | `44069a87…a47908e0e` | scored once, then diagnosed: spent |
| `sealed_jo2.py` (91) | `3a77bc40a6a95711b9978120511a6f665a6a8f8d1fb24d58588ca4b4dd572a2f` | scored once (2026-11-06): spent |

**The sealed sets are deliberately not in the repository.** That keeps their questions away from anyone tuning
the assistant. They exist only in the session scratchpad, which is temporary, so they will be lost when that
container is reclaimed. Because all three have now been scored, the next round needs a new sealed set anyway.
Full fingerprints, and the code fingerprints at each run, are in
`backend/src/ai/rag/eval/jordanian_round/FROZEN_CONFIG.sha256`.

## Evaluation harness (`backend/src/ai/rag/eval/jordanian_round/`)

- **Development and validation sets.** `dev_jo2.py`, `val_jo2.py`, plus the earlier pools `validation_set.py`,
  `sealed_set.py` and `sealed_set_v2.py`. The last two are former sealed sets, used as development data since
  they were scored.
- **Scripts:**
  - `rules_eval.py`: rules only, no model.
  - `diagnose.py` and `summarize.py`: per question, with the model.
  - `final_eval.py`: aggregate only, for sealed sets; needs the sealed files, which are not included.
  - `compare_models.py`: compares the models' saved readings.
- **Running them.** From `backend/` with `PYTHONPATH=.`, pass this directory as the first argument, e.g.
  `python src/ai/rag/eval/jordanian_round/rules_eval.py src/ai/rag/eval/jordanian_round dev_jo2 DEV_JO2 -v`. The model
  scripts need a GGUF file (the Qwen3-4B Q4_K_M used here came from the Docker Hub `ai/` catalogue) and
  `llama-cpp-python`.
- **Labels.** All sets are author-written (by an AI) and **not reviewed by a native Jordanian speaker**.

## Remaining RAG gaps

1. **Jordanian accuracy is 92.3% on the final set, below 95%.**
   - Weakest: customers/reviews 0/2, ambiguous questions 4/6, profit 13/15, multi-part 10/12.
   - Known misses on development and validation data: typos («امبارخ», «الربخ»), short product names («الدبس»),
     «طلبية» used for restocking or capacity, and market comparison read as market research rather than competitors.
2. **Native-speaker review.** No set has been reviewed by a native speaker. Some "errors" may be label choices,
   e.g. debts → sales because invoices hold payment status, and competitors vs market research.
3. **Speed.** The local CPU reader takes 7–15 s per call, too slow for the < 3 s goal. It stays off in production.
   Production answer latency (Groq) has not been measured, because the Groq key in this environment is rejected.
4. **Answer quality.** Correctness, faithfulness and citation accuracy with a model writing the answer were not
   measured here: no working model key.
5. **Debts.** Debt and receivable questions are understood, but KEEL has no receivables records for the
   assistant. A data-source change needs approval.
6. **Embeddings.** Hugging Face downloads fail with 401 here, so the production static embedding model could not be
   loaded locally. Document search was keyword-only in these runs.
7. **Next sealed set.** All three sealed sets are spent; the next round needs a new, ideally native-reviewed one.

## Unfinished tasks waiting for a decision

- **Assistant improvement plan** (`docs/ASSISTANT_SPEED_SOCIAL_RESEARCH_PLAN.md`): approved, not started. Order:
  speed → social conversation and dialect understanding → external research. It needs a working Hugging Face
  token (for the embedding model) and a Groq key, or another approved free provider.
- **Image generation.** My version (feature branch `claude/laughing-turing-w3psvt`, `8107ab1`) conflicts with main's
  `d1a6eeb`. The comparison was reported, and a port onto main awaits approval.
- **Forecasting phase.** Not started; waiting for approval.
- **Production (outside this scope, not changed here).** Cloudflare DNS for `keelai.net`, `www` and `api` points at
  `keel-frontend-staging` and `keel-ai-staging` hostnames on onrender.com, not at the KEEL services
  (`keel-web`, `ceopro-ai-new`). Render routes by domain, so it works today; repointing needs approval.
