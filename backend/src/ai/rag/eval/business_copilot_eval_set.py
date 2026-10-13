"""
KEEL - RAG Business Copilot Evaluation Set.

A real, representative question set for manually (or semi-automatically)
evaluating the chatbot - not a claim that the system is "fully evaluated"
just because this file exists. AI_ENGINEERING_PLAN.md's own tracking
table (line 136-137) had explicitly flagged "no formal IR benchmark" and
"no groundedness/citation-correctness eval dataset" as open gaps before
this file - this closes the "no dataset exists" half of that gap; running
it (manually, or via a future scoring harness) and interpreting the
results is a separate, ongoing activity this file does not itself claim
to have done.

## How to use this today

No automated scorer exists yet (a real, honest limitation - see this
module's own docstring end). Practical use today:

    from src.ai.rag.eval.business_copilot_eval_set import EVAL_QUESTIONS
    from src.ai.rag.llm_client import answer_query

    for case in EVAL_QUESTIONS:
        result = answer_query(conn, real_tenant_id, case["question"])
        print(case["id"], case["expected_grounding"], result["answer"])
        # then manually score against `notes` below

Each case's `expected_grounding` is one of the confidence states this
feature's own design calls for (never an exhaustive machine-checkable
oracle - a real business's actual data determines the true right answer,
which this file cannot know in advance):

- "structured_data": should be grounded in a live business_tools.py/
  structured_context.py/dashboard.* query, with an inline "(source: ...)"
  citation - a wrong or fabricated number here is a real bug.
- "application_knowledge": should be grounded in structured_summaries.py's
  platform-help/troubleshooting retrievable content.
- "market_external": may legitimately need web_fallback.py - only when
  the tenant's own market/competitor data is genuinely insufficient.
- "insufficient_data": the honest, CORRECT answer for a fresh/empty
  tenant is "I don't have that data yet" - scoring this as "wrong" because
  it didn't produce a confident number would be scoring honesty as a
  failure, exactly what this whole feature exists to avoid.
- "mixed": genuinely needs more than one of the above - the harder,
  multi-hop class of question this feature's own architecture doc names
  as the honest limit of what a keyword-gated single-pass prompt (no real
  multi-step agent loop yet) can reliably do.

`notes` records what a human reviewer should specifically check for that
question - not a generic rubric, but the real failure mode that question
is designed to catch (a fabricated number, a wrong-language reply, a
missing "I don't have this" disclosure, etc).
"""
from typing import TypedDict


class EvalCase(TypedDict):
    id: str
    category: str
    question: str
    expected_grounding: str
    notes: str


EVAL_QUESTIONS: list[EvalCase] = [
    # --- Application questions ("how do I use KEEL") ---------------------
    {
        "id": "app-01", "category": "application", "question": "How do I add a new product?",
        "expected_grounding": "application_knowledge",
        "notes": "Must describe the real Products page flow (structured_summaries.py's platform-help slot); never invent a button/screen name not in that content.",
    },
    {
        "id": "app-02", "category": "application", "question": "How do I create a marketing campaign?",
        "expected_grounding": "application_knowledge",
        "notes": "Should reference the real Marketing Studio flow (product/text/URL input, creative theme). Verify against the actual current frontend, not assumed UI text.",
    },
    {
        "id": "app-03", "category": "application", "question": "Where can I see my profit?",
        "expected_grounding": "application_knowledge",
        "notes": "Honest limit check: today there is no dedicated 'profit' page - the dashboard shows revenue, and the chatbot itself can now compute gross margin on request (business_tools.py). The answer should say both, not claim a profit page that doesn't exist.",
    },
    {
        "id": "app-04", "category": "application", "question": "كيف أضيف منافس جديد؟",
        "expected_grounding": "application_knowledge",
        "notes": "Arabic phrasing of 'how do I add a competitor' - answer must be in Arabic, matching the user's dialect, not switch to English.",
    },

    # --- Company/financial questions ----------------------------------------
    {
        "id": "fin-01", "category": "company_financial", "question": "Which products are most profitable?",
        "expected_grounding": "structured_data",
        "notes": "Must come from business_tools.py::build_financial_facts_block() (real gross-profit ranking), explicitly labeled GROSS margin, never a bare 'profit' claim with no cost caveat.",
    },
    {
        "id": "fin-02", "category": "company_financial", "question": "Where did my profit go?",
        "expected_grounding": "mixed",
        "notes": "The canonical example from the design brief - answer should state what changed (revenue/margin trend), name what data is missing (no fixed-cost/marketing-spend tracking), and NOT claim a full net-profit explanation. Score as a failure if it invents a fixed-cost figure.",
    },
    {
        "id": "fin-03", "category": "company_financial", "question": "Why did my revenue decrease?",
        "expected_grounding": "mixed",
        "notes": "No root-cause-attribution tool exists yet (confirmed gap - see architecture doc) - correct honest answer states the revenue trend number and says it cannot yet attribute WHY without more signals, rather than guessing a cause.",
    },
    {
        "id": "fin-04", "category": "company_financial", "question": "Which product is losing money?",
        "expected_grounding": "structured_data",
        "notes": "Must only name a product as losing money if business_tools.py's least_profitable entry actually has a negative gross_profit - never generalize a low-margin product into 'losing money.'",
    },
    {
        "id": "fin-05", "category": "company_financial", "question": "What are my biggest risks this week?",
        "expected_grounding": "mixed",
        "notes": "Real signal exists (insights/pipeline.py's proactive insights, already in structured_context.py) but a dedicated 'risk' framing doesn't - answer should draw on real insights/forecast/competitor-activity facts already available, not invent a risk score.",
    },
    {
        "id": "fin-06", "category": "company_financial", "question": "How much profit did my best-selling product generate?",
        "expected_grounding": "mixed",
        "notes": "Tests conversation-memory + financial-tool combination: 'my best-selling product' requires a prior turn's context (units_sold ranking) plus this turn's gross-profit lookup for that same product - the harder multi-hop case this pass's single-keyword-gated tool cannot fully resolve yet (see architecture doc's known limitation on this exact pattern).",
    },
    {
        "id": "fin-07", "category": "company_financial", "question": "What were my total profits last month?",
        "expected_grounding": "insufficient_data",
        "notes": "For a tenant with no cost_price data on any product: correct answer explicitly says cost data is missing, offers to compute it once cost_price is entered - never a fabricated number.",
    },

    # --- Market questions ----------------------------------------------------
    {
        "id": "mkt-01", "category": "market", "question": "Who are my strongest competitors?",
        "expected_grounding": "structured_data",
        "notes": "Grounded in tenant_competitors/global_competitors (structured_context.py) - names/tiers must be real, never invented.",
    },
    {
        "id": "mkt-02", "category": "market", "question": "What are competitors charging for this product?",
        "expected_grounding": "structured_data",
        "notes": "Grounded in dashboard/competitor_pricing.py's real matched prices - must say 'not available' if this product has no matched competitor prices, never estimate one.",
    },
    {
        "id": "mkt-03", "category": "market", "question": "What are the latest regulations affecting this product category?",
        "expected_grounding": "market_external",
        "notes": "Genuinely requires web_fallback.py - verify it actually fires (tenant's own data structurally can't answer this) and that every claim carries a real, clickable URL, dated.",
    },
    {
        "id": "mkt-04", "category": "market", "question": "What is the current market price of gold?",
        "expected_grounding": "market_external",
        "notes": "Tests the confidence gate's scoping to the tenant's own business_type/country - should not return generic global commodity data unrelated to the tenant's actual market unless genuinely relevant.",
    },

    # --- Mixed / multi-hop questions ------------------------------------------
    {
        "id": "mix-01", "category": "mixed", "question": "My sales increased but profits dropped. Why?",
        "expected_grounding": "mixed",
        "notes": "Needs revenue trend (dashboard/metrics.py-style) + margin trend (business_tools.py) + an honest 'here is what I can and cannot attribute this to' - the single hardest case in this set. A confident single-cause answer without hedging is a failure.",
    },
    {
        "id": "mix-02", "category": "mixed", "question": "Which competitor is closest to my price and how should I respond?",
        "expected_grounding": "mixed",
        "notes": "First half grounded (dashboard/competitor_pricing.py); second half ('how should I respond') is a real recommendation - must be reasoned from the actual positioning data, not a generic pricing-strategy platitude.",
    },
    {
        "id": "mix-03", "category": "mixed", "question": "Show me my best-selling product.",
        "expected_grounding": "structured_data",
        "notes": "Paired with mix-04 below to test conversation memory (design brief's own worked example).",
    },
    {
        "id": "mix-04", "category": "mixed", "question": "How much profit did it generate?",
        "expected_grounding": "mixed",
        "notes": "MUST be run as a second turn after mix-03 with real conversation history sent (now wired - see knowledgeBaseApi.js). 'It' must resolve to the product named in mix-03's answer, not a different/generic product. This is the direct verification of the 'follow-up question' worked example from the design brief.",
    },

    # --- Conflicting/uncertain data -------------------------------------------
    {
        "id": "conf-01", "category": "edge_case", "question": "hi",
        "expected_grounding": "insufficient_data",
        "notes": "A bare greeting - must get a short, warm reply, never a data dump just because structured facts happen to be non-empty (SYSTEM_PROMPT's own proportionality rule).",
    },
    {
        "id": "conf-02", "category": "edge_case", "question": "What is the weather today?",
        "expected_grounding": "insufficient_data",
        "notes": "Out of scope (SYSTEM_PROMPT's own scope rule) - must decline plainly and warmly, never attempt an answer, never trigger web fallback for something unrelated to the tenant's business.",
    },
]
