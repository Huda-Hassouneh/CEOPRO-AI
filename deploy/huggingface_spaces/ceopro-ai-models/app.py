"""CEOPRO AI - model-backed services (exact CEOPRO-AI models, unmodified)."""
import platform
from importlib import metadata

import gradio as gr
import spaces

import feature_market_intelligence
import feature_rag
import feature_sentiment

with gr.Blocks(title="CEOPRO AI - Models") as demo:
    gr.Markdown("# CEOPRO AI - Model services\n"
                "- [Sentiment Analysis](/sentiment) - API: `sentiment` (cardiffnlp/twitter-xlm-roberta-base-sentiment)\n"
                "- [Market Intelligence](/market-intelligence) - API: `market_intelligence` (sentiment model + Market Perception Index)\n"
                "- [RAG](/rag) - API: `rag_answer`, `embed` (paraphrase-multilingual-MiniLM-L12-v2), "
                "`rerank` (mmarco-mMiniLMv2-L12-H384-v1); LLM: Groq openai/gpt-oss-20b\n\n"
                "Every page runs the unmodified CEOPRO-AI implementation. See *Use via API* at the bottom of any page.")


@spaces.GPU(duration=1)
def _zerogpu_startup_requirement():
    """Never called. ZeroGPU hardware refuses to start a Space without at least one @spaces.GPU function;
    every CEOPRO-AI service here is CPU code (as CEOPRO-AI specifies) and runs in this process, outside the ZeroGPU quota."""
    return None


def versions() -> dict:
    """Exact runtime versions of the libraries this Space uses."""
    out = {"python": platform.python_version()}
    for p in ["gradio","spaces","torch","transformers","sentence-transformers","sentencepiece","faiss-cpu","rank-bm25","numpy","httpx","pdfplumber","python-docx","openpyxl"]:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


with demo:
    gr.api(versions, api_name="versions")

with demo.route("Sentiment Analysis", "/sentiment"):
    feature_sentiment.build_ui()
with demo.route("Market Intelligence", "/market-intelligence"):
    feature_market_intelligence.build_ui()
with demo.route("RAG", "/rag"):
    feature_rag.build_ui()

demo.queue(default_concurrency_limit=4).launch(show_error=True)
