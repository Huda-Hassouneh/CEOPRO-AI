"""CEOPRO AI - Pricing. Runs src/ai/pricing/pipeline.run_price_recommendation() unchanged (rule-based, no ML model)."""
import json
from datetime import datetime, timedelta, timezone

import gradio as gr

from memdb import MemConn
from src.ai.pricing import pipeline as pricing_pipeline

TENANT_ID = "public-demo-tenant"
PRODUCT_ID = "requested-product"

EXAMPLE_PRODUCT = {"product_name": "Premium Olive Oil 1L", "current_price": 24.50, "currency": "JOD", "cost_price": 17.00}
EXAMPLE_COMPETITORS = [
    {"competitor_name": "Rival Store", "price": 21.75, "currency": "JOD", "observed_at": "2026-10-01"},
    {"competitor_name": "City Market", "price": 22.40, "currency": "JOD", "observed_at": "2026-10-03"},
    {"competitor_name": "Family Grocer", "price": 20.90, "currency": "JOD", "observed_at": "2026-09-28"},
    {"competitor_name": "Gulf Online", "price": 119.00, "currency": "SAR", "observed_at": "2026-10-02"},
]
EXAMPLE_RATES = [{"from_currency": "SAR", "to_currency": "JOD", "rate": 0.189, "as_of": "2026-10-04", "source": "central-bank"}]


def _dt(v):
    d = datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _validate(product, competitors, rates):
    try:
        own = (product["product_name"], float(product["current_price"]), str(product["currency"]).upper(),
               float(product["cost_price"]) if product.get("cost_price") not in (None, "") else None)
        comps = [(f"price-{i}", f"competitor-{i}", c["competitor_name"], float(c["price"]), str(c["currency"]).upper(), _dt(c["observed_at"]))
                 for i, c in enumerate(competitors or [])]
        fx = {(r["from_currency"].upper(), r["to_currency"].upper()): (float(r["rate"]), _dt(r.get("as_of") or datetime.now(timezone.utc).date()), r.get("source", "caller"))
              for r in (rates or [])}
    except (KeyError, TypeError, ValueError) as exc:
        raise gr.Error(f"Invalid input: {exc}")
    return own, comps, fx


def _run(own, comps, fx):
    def competitor_rows(q, params):
        # Mirrors data_access._load_competitor_prices' WHERE: currency (= or !=) and freshness window.
        currency, days = params[2], int(params[3])
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        same = " cp.currency = " in q
        return [c for c in comps if ((c[4] == currency) == same) and c[5] >= cutoff]

    def rate_rows(q, params):
        r = fx.get((params[0], params[1]))
        return [r] if r else []

    conn = MemConn([(r"FROM products", lambda q, p: [own]),
                    (r"FROM competitor_prices", competitor_rows),
                    (r"FROM currency_rates", rate_rows)])
    try:
        result = pricing_pipeline.run_price_recommendation(conn, TENANT_ID, PRODUCT_ID)
    except ValueError as exc:
        return {"status": "ERROR", "error": str(exc)}, conn.persisted
    return result, conn.persisted


def recommend(product: dict, competitor_prices: list, exchange_rates: list = None) -> dict:
    """Price recommendation for one product vs. competitor prices."""
    own, comps, fx = _validate(product, competitor_prices, exchange_rates)
    result, persisted = _run(own, comps, fx)
    return {"result": result, "persisted_records": persisted}


def ui_recommend(product_json, competitors_json, rates_json):
    try:
        out = recommend(json.loads(product_json), json.loads(competitors_json), json.loads(rates_json or "[]"))
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Invalid JSON: {exc}")
    r = out["result"]
    ev = next((p for p in out["persisted_records"] if p["table"] == "evidence_records"), {})
    rec = next((p for p in out["persisted_records"] if p["table"] == "recommendation_outcomes"), {})
    md = (f"**Recommendation:** {rec.get('recommended_action', r.get('status'))}  \n**Confidence:** {r.get('confidence_score')}  \n"
          f"**Explanation:** {ev.get('explanation_text', '')}")
    return md, out


def build_ui():
    gr.Markdown("## CEOPRO AI - Pricing\nRule-based CEOPRO-AI price intelligence (`src/ai/pricing/pipeline.py`): same-currency market comparison, "
                "15% price-change guardrail, minimum-margin guardrail, cross-currency prices as reference only. No ML model is involved.")
    p_in = gr.Code(json.dumps(EXAMPLE_PRODUCT, indent=1), language="json", label="Product")
    c_in = gr.Code(json.dumps(EXAMPLE_COMPETITORS, indent=1), language="json", label="Competitor prices")
    r_in = gr.Code(json.dumps(EXAMPLE_RATES, indent=1), language="json", label="Exchange rates (optional)")
    btn = gr.Button("Recommend price", variant="primary")
    md = gr.Markdown()
    raw = gr.JSON(label="Raw output")
    btn.click(ui_recommend, [p_in, c_in, r_in], [md, raw], api_name="recommend_ui")
    gr.api(recommend, api_name="recommend")

