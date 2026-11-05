# Question-understanding benchmark (deterministic layer)

Measures `src/ai/rag/understanding.py` + `periods.py` — the rule layer that decides
**which evidence an assistant answer needs** (intents), **which dates** a question
means and **which catalog products** it names. It does not score LLM wording;
that needs a live model (see `../run_eval.py`).

## Splits

| File | Purpose | Rule |
|---|---|---|
| `dev.jsonl` | Diagnose and fix failures | May be inspected and tuned against. |
| `holdout.jsonl` | Independent estimate | Written together with `dev.jsonl` **before** the system was run on either (2026-11-05). Never inspect its per-item failures to change rules; only aggregate scores are reported. `holdout.sha256` pins its content. |

Once a holdout score has been reported after tuning, it is no longer "unseen" for
future work: add a new holdout split rather than reusing this one as independent
evidence after further rule changes.

## Labels

- `require`: intents the answer cannot be correct without.
- `forbid`: intents that would route to wrong evidence (e.g. *customers* read as *customs* → `trade`).
- `period`: `[start, end_exclusive]` (or a list of such pairs) for a fixed `today` of **2026-11-05**.
  Only unambiguous periods are labelled; "last week" (calendar convention varies by country) is not.
- `products`: catalog product ids from the synthetic catalog in `catalog.json` that must be resolved.
- `previous`: an earlier question in the same conversation (follow-up handling).
- `lang`: `en`, `ar` or `mixed`; `dialect`: `msa`, `levantine` (incl. Jordanian), `gulf`, `egyptian` or `none`.

An item is **correct** when every required intent is present, no forbidden intent
is present, and the period/products (when labelled) match exactly.

Run: `python -m scripts.evaluate_understanding` (from `backend/`).
