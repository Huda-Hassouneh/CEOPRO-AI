"""CEOPRO AI - Demand Forecasting. Runs src/ai/forecasting/pipeline.run_forecast() unchanged."""
import csv
import os
import io
from collections import defaultdict
from datetime import date

import gradio as gr

from memdb import MemConn
from src.ai.forecasting import pipeline as forecast_pipeline

TENANT_ID = "public-demo-tenant"
PRODUCT_ID = "requested-product"
EXAMPLE_CSV = open(os.path.join(os.path.dirname(__file__), "example_transactions.csv"), encoding="utf-8").read()


def _parse_transactions(transactions):
    """Accepts a list of {transaction_date, quantity, unit_price} dicts (CEOPRO import format)."""
    parsed = []
    for i, t in enumerate(transactions):
        try:
            parsed.append((date.fromisoformat(str(t["transaction_date"])[:10]), float(t["quantity"]), float(t["unit_price"])))
        except (KeyError, ValueError, TypeError) as exc:
            raise gr.Error(f"Transaction #{i + 1} is invalid ({exc}); need transaction_date (YYYY-MM-DD), quantity, unit_price.")
    if not parsed:
        raise gr.Error("Provide at least one transaction.")
    return parsed


def forecast(transactions: list, horizon_days: int = 7, current_price: float = None, current_stock: int = None, category: str = None, product_name: str = None) -> dict:
    """Demand forecast for one product from its sales transactions."""
    horizon_days = int(horizon_days or 7)
    names = sorted({t.get("product_name") for t in transactions if isinstance(t, dict) and t.get("product_name")})
    if product_name:
        transactions = [t for t in transactions if t.get("product_name") == product_name]
    elif len(names) > 1:
        raise gr.Error(f"Transactions contain {len(names)} products {names}; set product_name to forecast one of them.")
    if not 1 <= horizon_days <= 60:
        raise gr.Error("horizon_days must be between 1 and 60.")
    rows = _parse_transactions(transactions)

    def daily_rows(q, params):
        # Same aggregation as data_access.load_daily_demand's SQL: SUM(quantity), AVG(unit_price) per day.
        qty, prices = defaultdict(float), defaultdict(list)
        for d, q_, p in rows:
            qty[d] += q_
            prices[d].append(p)
        return [(d, qty[d], sum(prices[d]) / len(prices[d])) for d in sorted(qty)]

    def product_row(q, params):
        price = current_price if current_price not in (None, "") else rows[-1][2]
        return [(price, category, current_stock if current_stock not in (None, "") else None)]

    result, persisted = _run(daily_rows(None, None), product_row(None, None), horizon_days)
    return {"product_name": product_name or (names[0] if names else None), "transactions_used": len(rows),
            "result": result, "persisted_records": persisted}


def _run(daily, product, horizon_days):
    conn = MemConn([(r"FROM transactions", lambda q, p: daily), (r"FROM products", lambda q, p: product)])
    result = forecast_pipeline.run_forecast(conn, TENANT_ID, PRODUCT_ID, horizon_days=horizon_days)
    return result, conn.persisted


def _csv_to_transactions(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def ui_forecast(csv_text, product, horizon, price, stock):
    out = forecast(_csv_to_transactions(csv_text), horizon, price, stock, None, product or None)
    r = out["result"]
    ev = next((p for p in out["persisted_records"] if p["table"] == "evidence_records"), {})
    summary = (f"**Model used:** {r.get('source')}  \n**Expected demand on {r.get('forecast_target_date')}:** "
               f"{r.get('expected_demand'):.2f} units  \n**Confidence:** {r.get('confidence_score')}  \n"
               f"**Explanation:** {ev.get('explanation_text', '')}") if r.get("status") == "OK" else f"Status: {r.get('status')}"
    return summary, out


def build_ui():
    gr.Markdown("## CEOPRO AI - Demand Forecasting\nPaste one product's sales transactions in the CEOPRO import format "
                "(`transaction_date, quantity, unit_price`). Runs `src/ai/forecasting/pipeline.run_forecast()`: cold-start check, "
                "4 baselines, XGBoost walk-forward validation, and picks whichever wins.")
    csv_in = gr.Textbox(lines=12, label="Transactions CSV", value=EXAMPLE_CSV)
    product = gr.Textbox(value="Wireless Mouse Pro", label="Product name (required if the CSV has several products)")
    with gr.Row():
        horizon = gr.Number(value=7, precision=0, label="Horizon (days)")
        price = gr.Number(value=None, label="Current price (optional)")
        stock = gr.Number(value=None, precision=0, label="Current stock (optional)")
    btn = gr.Button("Forecast", variant="primary")
    summary = gr.Markdown()
    raw = gr.JSON(label="Raw output")
    btn.click(ui_forecast, [csv_in, product, horizon, price, stock], [summary, raw], api_name="forecast_ui")
    gr.api(forecast, api_name="forecast")

