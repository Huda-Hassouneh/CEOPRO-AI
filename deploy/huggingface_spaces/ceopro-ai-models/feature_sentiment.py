"""CEOPRO AI - Sentiment Analysis. Calls src/ai/sentiment/model.classify() unchanged."""
import gradio as gr

from src.ai.sentiment import model as sentiment_model

MAX_TEXTS = 64

# Load weights once at startup (same cache classify() uses).
_MODEL, _ = sentiment_model._get_model_and_tokenizer()
MODEL_REVISION = getattr(_MODEL.config, "_commit_hash", None) or "unknown"


def _classify(texts):
    return [p.as_dict() for p in sentiment_model.classify(texts)]


def analyze(texts: list) -> dict:
    """Classify Arabic/English texts. Input: list of strings. Output: per-text label + probabilities."""
    if isinstance(texts, str):
        texts = texts.splitlines()
    texts = [t.strip() for t in (texts or []) if isinstance(t, str) and t.strip()]
    if not texts:
        raise gr.Error("Provide at least one non-empty text.")
    if len(texts) > MAX_TEXTS:
        raise gr.Error(f"At most {MAX_TEXTS} texts per request.")
    preds = _classify(texts)
    return {"model": sentiment_model.MODEL_NAME, "model_revision": MODEL_REVISION,
            "results": [{"text": t, **p} for t, p in zip(texts, preds)]}


def ui_analyze(text_block: str):
    out = analyze(text_block.splitlines())
    rows = [[r["text"], r["label"], r["confidence"], r["positive_probability"], r["neutral_probability"], r["negative_probability"]]
            for r in out["results"]]
    return rows, out


def build_ui():
    gr.Markdown("## CEOPRO AI - Sentiment Analysis\nOne review per line (Arabic or English). Runs the CEOPRO-AI classifier "
                "`src/ai/sentiment/model.py` with `cardiffnlp/twitter-xlm-roberta-base-sentiment`.")
    inp = gr.Textbox(lines=6, label="Reviews (one per line)",
                     value="The delivery was fast and the product quality is excellent\nالخدمة سيئة جدا والتوصيل متأخر\nThe price is okay, nothing special")
    btn = gr.Button("Analyze", variant="primary")
    table = gr.Dataframe(headers=["text", "label", "confidence", "positive", "neutral", "negative"], label="Results")
    raw = gr.JSON(label="Raw output")
    btn.click(ui_analyze, inp, [table, raw], api_name="analyze_ui")
    # Integration endpoint: JSON list in, JSON out.
    gr.api(analyze, api_name="sentiment")

