"""
CEOPRO AI - Market Intelligence (Market Perception Index).
Chains two unmodified CEOPRO-AI pipelines over the submitted reviews:
  1. src/ai/sentiment/pipeline.classify_and_store_reviews()  - XLM-RoBERTa scoring
  2. src/ai/mpi/pipeline.get_subject_mpi()                   - recency/reliability-weighted 0-100 MPI
"""
import json
from datetime import date, datetime

import gradio as gr

from memdb import MemConn
from src.ai.mpi import pipeline as mpi_pipeline
from src.ai.mpi.scoring import RELIABILITY_WEIGHTS
from src.ai.sentiment import model as sentiment_model
from src.ai.sentiment import pipeline as sentiment_pipeline

TENANT_ID = "public-demo-tenant"
MAX_REVIEWS = 100
SUBJECT_TYPES = ("BUSINESS", "PRODUCT", "COMPETITOR")

_MODEL, _ = sentiment_model._get_model_and_tokenizer()
MODEL_REVISION = getattr(_MODEL.config, "_commit_hash", None) or "unknown"

EXAMPLE_REVIEWS = [
    {"text": "Great selection and the staff were really helpful", "review_date": "2026-09-30", "collection_method": "PUBLIC_API"},
    {"text": "الأسعار مرتفعة مقارنة بالمحلات الأخرى", "review_date": "2026-09-22", "collection_method": "PUBLIC_API"},
    {"text": "Fast delivery, product arrived well packaged", "review_date": "2026-09-15", "collection_method": "PUBLIC_FEED"},
    {"text": "خدمة العملاء ممتازة وسريعة في الرد", "review_date": "2026-08-30", "collection_method": "PUBLIC_API"},
    {"text": "The store was crowded and checkout took forever", "review_date": "2026-08-12", "collection_method": "MANUAL"},
    {"text": "Good quality olive oil, will buy again", "review_date": "2026-07-25", "collection_method": "PUBLIC_FEED"},
]


def _parse(reviews):
    parsed = []
    for i, r in enumerate(reviews or []):
        try:
            text = str(r["text"]).strip()
            d = datetime.fromisoformat(str(r["review_date"])[:10])
        except (KeyError, TypeError, ValueError) as exc:
            raise gr.Error(f"Review #{i + 1} invalid ({exc}); need text and review_date (YYYY-MM-DD).")
        if text:
            parsed.append({"review_id": f"review-{i + 1}", "text": text, "date": d,
                           "method": str(r.get("collection_method") or "MANUAL").upper()})
    if not parsed:
        raise gr.Error("Provide at least one review with text.")
    if len(parsed) > MAX_REVIEWS:
        raise gr.Error(f"At most {MAX_REVIEWS} reviews per request.")
    return parsed


def _run(parsed, subject_type, subject_id, country_code, as_of):
    by_id = {r["review_id"]: r for r in parsed}

    def unanalyzed(q, params):
        done = {p["review_id"] for p in conn.persisted if p["table"] == "sentiment_results"}
        return [(r["review_id"], r["text"], subject_type, subject_id if subject_type == "PRODUCT" else None,
                 subject_id if subject_type == "COMPETITOR" else None, None)
                for r in parsed if r["review_id"] not in done][: params[1]]

    def scored(q, params):
        # reviews JOIN sentiment_results: the rows step 1 just persisted.
        return [(p["review_id"], p["sentiment_label"].lower(), p["positive_probability"], p["negative_probability"],
                 by_id[p["review_id"]]["date"], by_id[p["review_id"]]["method"])
                for p in conn.persisted if p["table"] == "sentiment_results"]

    conn = MemConn([(r"FROM reviews r LEFT JOIN sentiment_results", unanalyzed),
                    (r"FROM reviews r JOIN sentiment_results", scored),
                    (r"country_code", lambda q, p: [(country_code,)] if country_code else [])])
    classified = sentiment_pipeline.classify_and_store_reviews(conn, TENANT_ID, batch_size=MAX_REVIEWS)
    mpi = mpi_pipeline.get_subject_mpi(conn, TENANT_ID, subject_type, subject_id, as_of=as_of)
    return classified, mpi, conn.persisted


def market_intelligence(reviews: list, subject_type: str = "BUSINESS", subject_id: str = None,
                        country_code: str = None, as_of: str = None) -> dict:
    """Score reviews for one subject (business, product or competitor) and compute its Market Perception Index."""
    subject_type = (subject_type or "BUSINESS").upper()
    if subject_type not in SUBJECT_TYPES:
        raise gr.Error(f"subject_type must be one of {SUBJECT_TYPES}")
    if subject_type == "BUSINESS":
        subject_id = None
    elif not subject_id:
        subject_id = f"{subject_type.lower()}-1"
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise gr.Error("as_of must be YYYY-MM-DD")
    parsed = _parse(reviews)
    classified, mpi, persisted = _run(parsed, subject_type, subject_id, country_code, as_of_date)
    texts = {r["review_id"]: r["text"] for r in parsed}
    per_review = [{"review_id": p["review_id"], "text": texts[p["review_id"]], "label": p["sentiment_label"],
                   "sentiment_score": p["sentiment_score"], "confidence": p["confidence"]}
                  for p in persisted if p["table"] == "sentiment_results"]
    evidence = next((p for p in persisted if p["table"] == "evidence_records"), None)
    return {"sentiment_model": sentiment_model.MODEL_NAME, "sentiment_model_revision": MODEL_REVISION,
            "classification": classified, "reviews": per_review, "mpi": mpi, "evidence_record": evidence}


def ui_run(reviews_json, subject_type, country_code, as_of):
    try:
        reviews = json.loads(reviews_json)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Invalid JSON: {exc}")
    out = market_intelligence(reviews, subject_type, None, country_code or None, as_of or None)
    m = out["mpi"]
    md = (f"### MPI: {m.get('mpi')} / 100\n**Status:** {m.get('status')} · **Reviews used:** {m.get('review_count')}  \n"
          f"**Explanation:** {(out['evidence_record'] or {}).get('explanation_text', '')}")
    rows = [[r["text"], r["label"], r["sentiment_score"], r["confidence"]] for r in out["reviews"]]
    return md, rows, out


def build_ui():
    gr.Markdown("## CEOPRO AI - Market Intelligence\nPaste reviews about your business, a product or a competitor. Each review is scored by the "
                "CEOPRO-AI sentiment pipeline (XLM-RoBERTa), then combined into the **Market Perception Index** (0-100) by `src/ai/mpi/` "
                f"with recency and source-reliability weighting. `collection_method` is one of {list(RELIABILITY_WEIGHTS)}.")
    rev_in = gr.Code(json.dumps(EXAMPLE_REVIEWS, indent=1, ensure_ascii=False), language="json", label="Reviews")
    with gr.Row():
        subj = gr.Dropdown(list(SUBJECT_TYPES), value="BUSINESS", label="Subject type")
        cc = gr.Textbox(value="JO", label="Country code (optional)")
        asof = gr.Textbox(value="", label="As-of date (optional, YYYY-MM-DD)")
    btn = gr.Button("Analyze market perception", variant="primary")
    md = gr.Markdown()
    table = gr.Dataframe(headers=["text", "label", "sentiment_score", "confidence"], label="Per-review sentiment")
    raw = gr.JSON(label="Raw output")
    btn.click(ui_run, [rev_in, subj, cc, asof], [md, table, raw], api_name="market_intelligence_ui")
    gr.api(market_intelligence, api_name="market_intelligence")

