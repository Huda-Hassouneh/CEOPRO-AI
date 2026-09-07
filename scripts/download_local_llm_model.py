"""
CEOPRO AI - One-Time Local LLM Model Download.

Fetches the exact GGUF model file docker-compose.yml's `llm-local` service
(and a bare `llama-server` run outside Docker) expects at ./models/ -
Qwen2.5-3B-Instruct, Q5_K_M quantization, from its official Hugging Face
repo. Live-verified 2026-09-06 against real hardware (i5-1135G7, 4 threads):
chosen over the smaller Q4_K_M quant because Q4 was NOT actually faster for
generation (5.54 tokens/sec vs Q5's 6.14) - there was no accuracy-for-speed
trade to make, so the higher-fidelity quant won outright.

Not committed to git (a 2.3GB binary has no business in a source repo) -
run this once per machine that needs the local LLM option:

    pip install huggingface_hub
    python scripts/download_local_llm_model.py

Then either:
    docker compose --profile local-llm up llm-local
or, without Docker:
    llama-server -m models/qwen2.5-3b-instruct-q5_k_m.gguf -t 4 --port 8090 -c 4096
    (get llama-server itself from https://github.com/ggml-org/llama.cpp/releases -
    the win-cpu-x64 build needs no compiler, no CMake, no llama-cpp-python
    package - see this session's own notes on why: no prebuilt wheel exists
    for very new Python versions, and this environment had no C++ toolchain
    to build one from source.)
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MODELS_DIR = REPO_ROOT / "models"

REPO_ID = "Qwen/Qwen2.5-3B-Instruct-GGUF"
FILENAME = "qwen2.5-3b-instruct-q5_k_m.gguf"


def main() -> int:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("huggingface_hub is not installed. Run: pip install huggingface_hub", file=sys.stderr)
        return 1

    MODELS_DIR.mkdir(exist_ok=True)
    print(f"Downloading {REPO_ID}/{FILENAME} (~2.3GB) to {MODELS_DIR} ...")
    path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME, local_dir=str(MODELS_DIR))
    print(f"Done: {path}")
    print(
        "\nNext step: docker compose --profile local-llm up llm-local\n"
        "(or run llama-server directly - see this script's own module docstring)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
