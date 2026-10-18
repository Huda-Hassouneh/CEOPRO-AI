# KEEL — Plan & Contract Update Tracker

**Owner:** AI/ML Engineering
**Tracks changes to:** `MASTER_SPEC_v4.md` (as it affects/is affected by AI scope), `AI_ENGINEERING_PLAN.md`, `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`, and any ownership-matrix entries in `src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md` that touch AI-owned data.
**Update convention:** append-only, date-stamped entries. Don't edit or delete past entries — if something is superseded, add a new entry that says so and link back. Mirrors the convention already used in `AI_PROGRESS.md` and `src/infrastructure/CONTRACT_CHANGELOG.md`.

---

## Precedence rule (governs every entry below)

When a planning document and the live, implemented schema/code disagree:

- **The implemented schema/code wins for anything already built.** Other teams may already be writing against it; renaming or re-shaping it after the fact breaks their code. The planning doc gets corrected to match reality.
- **The planning doc wins for anything not yet built.** An unbuilt table or field is still a valid requirement — it just hasn't landed yet. Keep pushing it as an ask.
- **Anything that is both already built *and* colliding with planned AI ownership** (two systems about to write the same data) is **not** resolved by this rule — it's flagged for an explicit human decision and stays open until someone with authority over both sides picks a direction.

---

## 2026-08-07 — Initial reconciliation audit (docs vs. live repo)

Compared `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`, `AI_ENGINEERING_PLAN.md`, and `AI_PROGRESS.md` against the actual `src/infrastructure/database/init_schema.sql` and `src/infrastructure/messaging/ai_consumer.py` in the live repo. Findings and resolutions:

| Item | Planning doc said | Live repo has | Resolution | Status |
|---|---|---|---|---|
| Tenant country field | `companies.tenant_country VARCHAR(2)` needs adding (contract-changes §1.1, blocking ask #1) | `companies.country_code VARCHAR(2) NOT NULL` — no default — already live, along with `operating_countries`, `primary_currency`, `supported_currencies`, `timezone`, `preferred_language`, `supported_languages` | **Schema wins.** AI code targets `country_code`, not `tenant_country`. Every `companies` insert must set it explicitly — there is no default to fall back on. | ✅ Resolved — blocking ask #1 downgraded from 🔴 to closed |
| Evidence table | Propose new `ai_evidence` table (contract-changes §2 ownership matrix) | `evidence_records` already exists and already has the exact FACT/PREDICTION/RECOMMENDATION/ASSUMPTION/UNKNOWN check constraint, `model_version`, `confidence_score`, `source_record_ids` (JSONB), `country_context` | **Schema wins.** Module J (evidence tagging) targets `evidence_records`. Drop the `ai_evidence` line from the ownership matrix — a second table would fork the evidence trail rather than extend it. | ✅ Resolved |
| Model registry table | Propose new `model_registry` table (contract-changes §2, Module K) | `model_versions` already exists (`status` enum: development/candidate/staging/production/archived, `metrics` JSONB) — but **no artifact-path column** | **Hybrid.** Module K targets `model_versions`, not a new table. The missing artifact path (needed to point at the MinIO object for a trained model) becomes a new, small ask instead of a new table: `ALTER TABLE model_versions ADD COLUMN artifact_path VARCHAR(500);` | 🟡 Partially resolved — new ask open, owner: Backend/DB |
| pgvector / `knowledge_chunks` | Needed, blocking (contract-changes §1.2) | Not present — no `vector` extension, no `knowledge_chunks` table. `rag_documents_metadata` (the FK target for it) does already exist. | **Doc wins — still a valid, still-blocking ask.** No change. | 🔴 Still blocking |
| Row-Level Security | Needed, blocking (contract-changes §1.3) | No RLS/`CREATE POLICY` statements anywhere in `init_schema.sql` | **Doc wins — still a valid, still-blocking ask.** No change. | 🔴 Still blocking |
| `currency_rates` table | Needed for cross-currency logic (contract-changes §1.1/§4) | Not present | **Doc wins — still a valid, still-blocking ask** (for cross-currency logic only; single-currency logic is unaffected). | 🔴 Still blocking (cross-currency only) |
| `ai_consumer.py` scope collision | Not mentioned in any AI doc | `src/infrastructure/messaging/ai_consumer.py` already consumes `market.intelligence.raw` and writes to `evidence_records`, under infra's ownership rather than `src/ai/` — functionally overlapping with what Module E/J are scoped to own | **Not resolved by the precedence rule** — this is a live collision, not a naming mismatch. Needs an explicit decision: does this consumer get retired/migrated into `src/ai/` when Module E lands, or does AI design Module E to coexist with it without double-writing `evidence_records`? | 🟠 Open — escalated, needs owner decision |
| Hardcoded DB credential | N/A | `ai_consumer.py` has a hardcoded Postgres password as its `DATABASE_URL` fallback default | Flagged to infra regardless of AI scope — it's in a public repo. Not an AI-owned fix, but blocking it silently would be irresponsible. | 🟠 Open — escalated, owner: whoever owns `ai_consumer.py` |

**Net effect on `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`'s blocking-asks table:** asks #1 (country/currency) closes. Asks #2 (pgvector), #3 (RLS) stand as-is. A new, smaller ask (artifact_path column) replaces the "new `model_registry` table" idea, and two new escalation items (`ai_consumer.py` collision + hardcoded credential) are added, outside the original five.

---

## 2026-08-07 — Master spec added to repo

`Version_4.txt` (the master spec shared across all teams) added to the repo as `MASTER_SPEC_v4.md` — content unchanged, only Markdown section headers added at each `====`-delimited section for GitHub readability/navigation. This file is the source of truth referenced throughout `AI_ENGINEERING_PLAN.md` and `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`; it wasn't previously in version control, so those documents' section references (e.g. "Section 9", "Section 37") were previously unverifiable by anyone without the original file. They now resolve to headings in this repo.

---

## 2026-10-16 — Competitor relevance: contract review (additive; spec S20 / S22 / S19 alignment)

Compared the competitor-relevance work (category-aware tiers, confidence score, directory ordering) against the contracts it touches. Full field-level list: `src/infrastructure/CONTRACT_CHANGELOG.md` (2026-10-16).

| Contract | Finding | Resolution |
|---|---|---|
| Spec S22 — one shared evidence architecture, "confidence must not be implemented independently" | The first version stored a bespoke confidence score with no evidence record. | **Spec wins.** Each classification outcome now writes a shared `evidence_records` row (`competitor_classification`; `FACT`/`UNKNOWN`), de-duplicated so re-scoring an unchanged competitor adds nothing; linked via `tenant_competitors.evidence_id`. |
| Spec S20 — ranking transparent, weights configurable | Weights were constants; no breakdown. | **Spec wins.** `COMPETITOR_CONFIDENCE_WEIGHTS` + per-call override; every row returns `confidence_breakdown` and `confidence_reasons`. |
| Spec S19 — foreign competitors not automatically direct competitors | Seeded retailers were US-only for every tenant. | **Spec wins.** Seeded retailers geo-scoped (`retailer_geo.py`). |
| Spec S29 — APIs support filtering/pagination | `/dashboard/competitors` had neither. | Added optional `min_confidence`, `max_distance_km`, `limit`, `offset`. |
| Frontend contract for `/dashboard/competitors` (documented as the "final backend contract") | First version changed `summary_line` wording and silently moved weak rows to a new group. | **Contract wins.** `summary_line` restored byte-for-byte (new text lives in `confidence_summary`); weak-lead split is opt-in (`separate_weak_leads`). Remaining intentional changes: ordering (alphabetical -> confidence) and CANDIDATE now excluding different-category businesses — both requested product behaviour, listed in the changelog. |
| Multi-tenancy / RLS (PR checklist) | Prior competitor tests ran as superuser, proving nothing about RLS (cf. PENDING_ACTIONS #32). | New `test_competitor_relevance_rls_integration_db.py` runs classification, evidence, refresh, directory, shared GLOBAL rows and cross-tenant isolation as the real `ceopro_app` role. |

---

## How to add an entry

1. New date-stamped `##` section at the bottom (never edit history).
2. State what changed, what it was compared against, and which side of the precedence rule it falls under (or that it's an open escalation).
3. If it closes or reopens an item in `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`'s summary table, say so explicitly and update that table's status column to match.
4. If it changes a module's blocked/unblocked status in `AI_PROGRESS.md`, update that file's Module status table in the same commit.
