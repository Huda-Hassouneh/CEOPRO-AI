"""CEOPRO AI - Analytics services (deterministic / statistical CEOPRO-AI functionality, no invented ML models)."""
import platform
from importlib import metadata

import gradio as gr
import spaces

import feature_extraction
import feature_forecasting
import feature_pricing

with gr.Blocks(title="CEOPRO AI - Analytics") as demo:
    gr.Markdown("# CEOPRO AI - Analytics services\n"
                "- [Extraction](/extraction) - API: `extract_file`, `extract_text`\n"
                "- [Demand Forecasting](/forecasting) - API: `forecast`\n"
                "- [Pricing](/pricing) - API: `recommend`\n\n"
                "Every page runs the unmodified CEOPRO-AI implementation. See *Use via API* at the bottom of any page.")


@spaces.GPU(duration=1)
def _zerogpu_startup_requirement():
    """Never called. ZeroGPU hardware refuses to start a Space without at least one @spaces.GPU function;
    every CEOPRO-AI service here is CPU code (as CEOPRO-AI specifies) and runs in this process, outside the ZeroGPU quota."""
    return None


def versions() -> dict:
    """Exact runtime versions of the libraries this Space uses."""
    out = {"python": platform.python_version()}
    for p in ["gradio","spaces","xgboost","scikit-learn","pandas","numpy","pdfplumber","openpyxl"]:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


with demo:
    gr.api(versions, api_name="versions")

with demo.route("Extraction", "/extraction"):
    feature_extraction.build_ui()
with demo.route("Demand Forecasting", "/forecasting"):
    feature_forecasting.build_ui()
with demo.route("Pricing", "/pricing"):
    feature_pricing.build_ui()

demo.queue(default_concurrency_limit=4).launch(show_error=True)
