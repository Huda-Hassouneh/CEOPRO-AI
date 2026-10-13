"""
KEEL - Business Copilot Evaluation Harness (B12, Phase 2).

PR #7 shipped a 20-question dataset (business_copilot_eval_set.py) with no
scoring harness around it - this is that harness, honestly scoped:

## What this actually checks (three independent, honestly-labeled modes)

1. **Deterministic gate-selection check** (default, always runs - no DB, no
   LLM, no network). For each eval case, checks whether the question's own
   text actually triggers the keyword gates
   (business_tools.is_financial_question, orchestrator.py's intent
   matchers, application_registry.search_features) that its
   `expected_grounding` implies it should. This is real signal about
   whether the orchestration layer AS BUILT can even attempt the right
   kind of grounding - it is explicitly NOT a judgment of answer
   correctness, since no LLM call happens in this mode. Categories that
   cannot be predicted from keywords alone (market_external,
   insufficient_data - both depend on runtime data state, not question
   text) are marked "not statically checkable" rather than given a
   fabricated pass/fail.

2. **Live-DB check** (`--live-db`, needs AI_TEST_DATABASE_URL +
   APP_DB_PASSWORD). Seeds one real tenant with real data, actually runs
   the tool-registry functions each case's gate selected, and checks for
   real citation markers ("(source:") in the resulting facts blocks - a
   real, if narrow, groundedness/non-fabrication signal, still with no
   LLM call.

3. **Live-LLM check** (`--live-llm`, needs a real GROQ_API_KEY AND
   outbound network access to Groq). Actually calls answer_query() end to
   end for each case. If this mode is requested but the environment
   cannot reach Groq (no key, or a network error), the report says so
   explicitly - this harness NEVER fabricates an LLM response or reports
   a live-LLM result that didn't really happen.

Usage:
    python -m src.ai.rag.eval.run_eval                  # mode 1 only
    python -m src.ai.rag.eval.run_eval --live-db         # + mode 2
    python -m src.ai.rag.eval.run_eval --live-llm        # + mode 3 (attempted)
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from src.ai.rag import orchestrator as _orchestrator
from src.ai.rag.business_tools import is_financial_question
from src.ai.rag.eval.business_copilot_eval_set import EVAL_QUESTIONS

# Real, observed root cause (2026-09-27, live-llm-verification.yml): this
# module's own 6 back-to-back real Groq calls, plus
# scripts/live_llm_verification.py's ~7 more right after it in the same
# CI job, can exhaust Groq's free-tier 8000-tokens-per-minute rolling
# budget on their own - each of this app's structured-facts-heavy RAG
# prompts costs ~2500-3600 tokens, so 2-3 unspaced calls alone can hit
# the cap. Spacing calls apart (rather than firing all 6 within seconds)
# matches the rate limit's own rolling-window shape.
LIVE_LLM_CALL_SPACING_SECONDS = float(os.getenv("LIVE_LLM_CALL_SPACING_SECONDS", "30"))


def _predict_gate_hits(question_text: str) -> dict:
    """Mirrors orchestrator.py's REAL gate conditions exactly (not a
    looser approximation) - build_tool_facts_blocks() only calls
    search_application_knowledge when _APPLICATION_HELP_KEYWORDS matches,
    never on search_features() alone, so this must match that exactly or
    this harness would report a gate as "fired" that production code
    never actually calls."""
    lowered = question_text.lower()
    return {
        "financial": is_financial_question(question_text),
        "application_knowledge": _orchestrator._matches(lowered, _orchestrator._APPLICATION_HELP_KEYWORDS),
        "top_products": _orchestrator._matches(lowered, _orchestrator._TOP_PRODUCTS_KEYWORDS),
        "inventory": _orchestrator._matches(lowered, _orchestrator._INVENTORY_KEYWORDS),
        "competitors": _orchestrator._matches(lowered, _orchestrator._COMPETITOR_KEYWORDS),
        "demand_forecast": _orchestrator._matches(lowered, _orchestrator._DEMAND_FORECAST_KEYWORDS),
        "marketing": _orchestrator._matches(lowered, _orchestrator._MARKETING_KEYWORDS),
        "root_cause": _orchestrator._matches(lowered, _orchestrator._ROOT_CAUSE_KEYWORDS),
    }


def run_deterministic_gate_check() -> list:
    """Returns a list of per-case result dicts. Never raises - a
    statically-unpredictable category is reported as such, not skipped
    silently."""
    results = []
    for case in EVAL_QUESTIONS:
        hits = _predict_gate_hits(case["question"])
        any_business_data_hit = any([hits["financial"], hits["top_products"], hits["inventory"], hits["competitors"], hits["demand_forecast"], hits["marketing"], hits["root_cause"]])

        expected = case["expected_grounding"]
        if expected == "application_knowledge":
            verdict = "PASS" if hits["application_knowledge"] else "FAIL"
        elif expected == "structured_data":
            verdict = "PASS" if any_business_data_hit else "FAIL"
        else:
            # "mixed" cases (per business_copilot_eval_set.py's own
            # docstring) may legitimately be grounded by the ALWAYS-ON
            # structured_context.py::build_structured_facts_block() -
            # e.g. fin-05 ("biggest risks") is grounded by the existing
            # proactive-insights block, not by any Phase-2 keyword gate
            # this harness checks. A Phase-2 gate not firing on a "mixed"
            # case is therefore not necessarily a failure - reported as
            # informational, not scored, to avoid a false FAIL against
            # machinery outside this harness's own checkable scope.
            # market_external / insufficient_data are separately
            # unpredictable from question text alone (they depend on
            # runtime data state) - never fabricate a verdict for either.
            verdict = "INFORMATIONAL" if expected == "mixed" else "NOT_STATICALLY_CHECKABLE"

        results.append({
            "id": case["id"], "category": case["category"], "expected_grounding": expected,
            "gate_hits": {k: v for k, v in hits.items() if v}, "verdict": verdict,
        })
    return results


def _seed_live_tenant(conn):
    """Seeds one real tenant with a modest amount of real data (a product,
    a sale, a competitor) - enough for the tool-registry functions to have
    something real to return, so a citation-marker check means something."""
    cursor = conn.cursor()
    tenant_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Eval Harness Co', 'JO', 'JOD');",
        (tenant_id,),
    )
    product_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) VALUES (%s, %s, %s, 10.0, 4.0, 'JOD');",
        (product_id, tenant_id, json.dumps({"en": "Eval Widget"})),
    )
    invoice_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    cursor.execute(
        "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) VALUES (%s, %s, %s, %s, 100.0, 100.0, 'JOD');",
        (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", now - timedelta(days=3)),
    )
    cursor.execute(
        "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) VALUES (%s, %s, %s, 10, 10.0, 100.0);",
        (tenant_id, invoice_id, product_id),
    )
    conn.commit()
    return tenant_id


def run_live_db_check() -> dict:
    """Returns {"ran": bool, "reason": str|None, "results": [...]}."""
    database_url = os.getenv("AI_TEST_DATABASE_URL")
    app_db_password = os.getenv("APP_DB_PASSWORD")
    if not database_url or not app_db_password:
        return {"ran": False, "reason": "AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set", "results": []}

    import psycopg2
    conn = psycopg2.connect(database_url)
    try:
        tenant_id = _seed_live_tenant(conn)
        results = []
        for case in EVAL_QUESTIONS:
            hits = _predict_gate_hits(case["question"])
            if not any(hits.values()):
                continue  # no gate fired - nothing to check for this case in this mode
            financial_text = ""
            if hits["financial"]:
                from src.ai.rag.business_tools import build_financial_facts_block
                financial_text = build_financial_facts_block(conn, tenant_id, case["question"])
            tool_blocks = _orchestrator.build_tool_facts_blocks(conn, tenant_id, case["question"])
            combined_text = financial_text + "\n" + "\n".join(text for _, text in tool_blocks)
            has_citation_marker = "(source:" in combined_text or "source:" in combined_text
            results.append({
                "id": case["id"],
                "gates_fired": [k for k, v in hits.items() if v],
                "produced_output": bool(combined_text.strip()),
                "has_citation_marker": has_citation_marker,
            })
        return {"ran": True, "reason": None, "results": results}
    finally:
        conn.rollback()
        conn.close()


def run_live_llm_check() -> dict:
    """Returns {"ran": bool, "reason": str|None, "results": [...]}. Only
    ATTEMPTS a real call - if GROQ_API_KEY is unset, or the call fails
    (including for network-restricted sandboxes), reason explains exactly
    why, and no fabricated answer is ever reported as if it came from the
    model."""
    if not os.getenv("GROQ_API_KEY") and not os.getenv("LOCAL_LLM_BASE_URL") and not os.getenv("PAID_LLM_BASE_URL"):
        return {"ran": False, "reason": "No LLM provider configured (GROQ_API_KEY/LOCAL_LLM_BASE_URL/PAID_LLM_BASE_URL all unset)", "results": []}

    database_url = os.getenv("AI_TEST_DATABASE_URL")
    if not database_url:
        return {"ran": False, "reason": "AI_TEST_DATABASE_URL not set - live-LLM mode also needs a real tenant to query against", "results": []}

    import psycopg2
    from src.ai.rag.llm_client import LLMError, answer_query

    conn = psycopg2.connect(database_url)
    try:
        tenant_id = _seed_live_tenant(conn)
        results = []
        for i, case in enumerate(EVAL_QUESTIONS[:6]):  # bounded - this is a real, rate-limited API call per case
            if i > 0:
                time.sleep(LIVE_LLM_CALL_SPACING_SECONDS)
            try:
                response = answer_query(conn, tenant_id, case["question"])
                results.append({"id": case["id"], "ok": True, "answer_preview": response["answer"][:200], "source_count": len(response["sources"])})
            except LLMError as exc:
                results.append({"id": case["id"], "ok": False, "error": str(exc)})
        return {"ran": True, "reason": None, "results": results}
    except Exception as exc:  # network failure, DNS, etc. - report, don't hide
        return {"ran": False, "reason": f"Live-LLM attempt raised: {exc}", "results": []}
    finally:
        conn.rollback()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-db", action="store_true", help="Also run the live-DB tool-output check")
    parser.add_argument("--live-llm", action="store_true", help="Also attempt a real end-to-end LLM call per case (bounded to 6 cases)")
    args = parser.parse_args()

    print("=" * 70)
    print("KEEL Business Copilot Evaluation Harness")
    print("=" * 70)

    gate_results = run_deterministic_gate_check()
    passed = sum(1 for r in gate_results if r["verdict"] == "PASS")
    failed = sum(1 for r in gate_results if r["verdict"] == "FAIL")
    informational = sum(1 for r in gate_results if r["verdict"] == "INFORMATIONAL")
    not_checkable = sum(1 for r in gate_results if r["verdict"] == "NOT_STATICALLY_CHECKABLE")
    print(
        f"\n[Mode 1: Deterministic gate-selection check] {passed} PASS / {failed} FAIL / "
        f"{informational} informational (mixed-category, not scored) / {not_checkable} not statically checkable "
        f"(of {len(gate_results)} cases)"
    )
    for r in gate_results:
        if r["verdict"] == "FAIL":
            print(f"  FAIL {r['id']} ({r['category']}): expected {r['expected_grounding']}, gates fired: {r['gate_hits']}")
        elif r["verdict"] == "INFORMATIONAL":
            print(f"  info {r['id']} ({r['category']}): gates fired: {r['gate_hits'] or '(none - may rely on the always-on structured facts block)'}")

    if args.live_db:
        live_db = run_live_db_check()
        if live_db["ran"]:
            with_citation = sum(1 for r in live_db["results"] if r["has_citation_marker"])
            print(f"\n[Mode 2: Live-DB check] ran against a real seeded tenant. {len(live_db['results'])} cases had a gate fire; {with_citation} produced a citation marker.")
            for r in live_db["results"]:
                if not r["has_citation_marker"]:
                    print(f"  NO CITATION MARKER: {r['id']} (gates: {r['gates_fired']})")
        else:
            print(f"\n[Mode 2: Live-DB check] NOT RUN - {live_db['reason']}")

    if args.live_llm:
        live_llm = run_live_llm_check()
        if live_llm["ran"]:
            ok_count = sum(1 for r in live_llm["results"] if r["ok"])
            print(f"\n[Mode 3: Live-LLM check] ran {len(live_llm['results'])} real calls, {ok_count} succeeded.")
            for r in live_llm["results"]:
                print(f"  {r['id']}: {'OK' if r['ok'] else 'ERROR - ' + r.get('error', '')}")
        else:
            print(f"\n[Mode 3: Live-LLM check] NOT RUN - {live_llm['reason']}")

    print("\n" + "=" * 70)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
