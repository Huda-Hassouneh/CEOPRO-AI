"""
KEEL image server - a self-hosted text-to-image service that KEEL's
"local" image provider talks to (src/ai/marketing/image_generation.py,
LOCAL_IMAGE_BASE_URL / LOCAL_IMAGE_BASE_URLS).

It runs an open-weight diffusion model with Hugging Face `diffusers` on
whatever the machine has: an NVIDIA GPU (float16), else the CPU (bfloat16
when the CPU supports it - fast on Intel CPUs with AMX - otherwise
float32). There is no per-image charge: the only cost is the machine.

Default model: Stable Diffusion XL 1.0 base (Stability AI), licence
CreativeML Open RAIL++-M - commercial use of the model and of the images
is allowed, subject to the licence's use restrictions (Attachment A: no
unlawful, harmful, deceptive or discriminatory uses). How to obtain it for
free: scripts/fetch_image_model.sh (docker.io/ai/stable-diffusion, Docker
Hub's official model catalog). Any other diffusers text-to-image folder
works through KEEL_IMAGE_MODEL_DIR; check its licence first.

API (the subset of OpenAI's images API KEEL uses, plus seed):
  POST /v1/images/generations
       {"prompt": str, "size": "WxH", "n": 1, "response_format": "b64_json",
        "seed": int?, "negative_prompt": str?, "steps": int?}
    -> {"created": ts, "data": [{"b64_json": ..., "seed": int}],
        "timings": {"seconds": float}}
    503 + Retry-After while another image is being made (one at a time:
    a diffusion model uses every core / the whole GPU).
  GET /health -> model, device, dtype, busy, images made, average seconds
       per image, memory in use.

Run:  KEEL_IMAGE_MODEL_DIR=/models/sdxl-base-1.0 \\
      uvicorn image_server.server:app --host 0.0.0.0 --port 7860
"""
import base64
import io
import logging
import os
import random
import threading
import time
from collections import deque
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("keel.image_server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MODEL_DIR = os.getenv("KEEL_IMAGE_MODEL_DIR", "/models/sdxl-base-1.0")
DEFAULT_STEPS = int(os.getenv("KEEL_IMAGE_STEPS", "20"))
MAX_STEPS = int(os.getenv("KEEL_IMAGE_MAX_STEPS", "50"))
GUIDANCE = float(os.getenv("KEEL_IMAGE_GUIDANCE", "6.0"))
# About 1.4 megapixels: SDXL's trained range. Bigger requests are refused,
# not silently shrunk, so the caller always gets the shape it asked for.
MAX_PIXELS = int(os.getenv("KEEL_IMAGE_MAX_PIXELS", str(1408 * 1024)))
OUTPUT_FORMAT = os.getenv("KEEL_IMAGE_OUTPUT", "jpeg").lower()  # jpeg (smaller files) or png
JPEG_QUALITY = int(os.getenv("KEEL_IMAGE_JPEG_QUALITY", "93"))
API_KEY = os.getenv("KEEL_IMAGE_API_KEY", "")
# Making one 1024x1024 image needs about 0.5-1 GB on top of the loaded model.
# Below this much free memory the server answers "busy" (the KEEL worker
# retries later) instead of starting an image the kernel may kill it for -
# seen for real on a 16 GB machine also running the copy model.
MIN_FREE_GB = float(os.getenv("KEEL_IMAGE_MIN_FREE_GB", "1.5"))
DEFAULT_NEGATIVE = os.getenv(
    "KEEL_IMAGE_NEGATIVE_PROMPT",
    "text, letters, words, watermark, logo, signature, blurry, low quality, jpeg artifacts, deformed, "
    "disfigured, extra fingers, nsfw, nudity",
)

app = FastAPI(title="KEEL image server")
_lock = threading.Lock()
_state = {"pipe": None, "device": None, "dtype": None, "load_seconds": None, "made": 0, "failed": 0,
          "recent": deque(maxlen=50), "error": None}


def _pick_device():
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.float16
    forced = os.getenv("KEEL_IMAGE_DTYPE", "").lower()
    if forced in ("float32", "fp32"):
        return "cpu", torch.float32
    try:  # bfloat16 is only worth it where the CPU computes it natively (AVX512-BF16 / AMX)
        flags = open("/proc/cpuinfo").read()
        if forced in ("bfloat16", "bf16") or "avx512_bf16" in flags or "amx_bf16" in flags:
            return "cpu", torch.bfloat16
    except OSError:
        pass
    return "cpu", torch.float32


def load_pipeline():
    """Loads the model once (about 10 s from local disk; about 7 GB of RAM in
    bfloat16, more while loading)."""
    import torch
    from diffusers import AutoPipelineForText2Image, DPMSolverMultistepScheduler

    device, dtype = _pick_device()
    if device == "cpu":
        torch.set_num_threads(int(os.getenv("KEEL_IMAGE_THREADS", str(os.cpu_count() or 4))))
    started = time.monotonic()
    pipe = AutoPipelineForText2Image.from_pretrained(MODEL_DIR, torch_dtype=dtype, use_safetensors=True)
    # DPM-Solver++ (Karras sigmas): good images in about 20 steps instead of 30-50.
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    pipe.set_progress_bar_config(disable=True)
    pipe = pipe.to(device)
    _state.update(pipe=pipe, device=device, dtype=str(dtype).replace("torch.", ""),
                  load_seconds=round(time.monotonic() - started, 1))
    logger.info("model %s loaded on %s/%s in %.1fs", MODEL_DIR, device, _state["dtype"], _state["load_seconds"])
    return pipe


@app.on_event("startup")
def _startup():
    if os.getenv("KEEL_IMAGE_LAZY_LOAD", "false").lower() != "true":
        try:
            load_pipeline()
        except Exception as err:  # noqa: BLE001 - /health reports it; requests get 503
            _state["error"] = f"{type(err).__name__}: {err}"
            logger.exception("model failed to load")


def _authorised(authorization: Optional[str] = Header(default=None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="invalid image server key")


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: str = Field(default="1024x1024", pattern=r"^\d{3,4}x\d{3,4}$")
    n: int = Field(default=1, ge=1, le=4)
    response_format: str = Field(default="b64_json", pattern="^b64_json$")
    seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)
    negative_prompt: Optional[str] = Field(default=None, max_length=1000)
    steps: Optional[int] = Field(default=None, ge=1)
    model: Optional[str] = None  # accepted for OpenAI compatibility; this server has one model


def _encode(image) -> str:
    buffer = io.BytesIO()
    if OUTPUT_FORMAT == "png":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return base64.b64encode(buffer.getvalue()).decode()


def _available_gb() -> Optional[float]:
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except Exception:  # noqa: BLE001 - no psutil: no guard
        return None


def _average_seconds() -> Optional[float]:
    recent = list(_state["recent"])
    return round(sum(recent) / len(recent), 1) if recent else None


@app.post("/v1/images/generations", dependencies=[Depends(_authorised)])
def generate(body: GenerationRequest):
    import torch

    width, height = (int(v) for v in body.size.split("x"))
    if width % 8 or height % 8:
        raise HTTPException(status_code=400, detail="width and height must be multiples of 8")
    if width * height > MAX_PIXELS or min(width, height) < 256:
        raise HTTPException(status_code=400, detail=f"size must be at least 256 px a side and at most {MAX_PIXELS} pixels")
    steps = min(body.steps or DEFAULT_STEPS, MAX_STEPS)
    if _state["pipe"] is None:
        detail = "model not loaded" + (f": {_state['error']}" if _state["error"] else "")
        return JSONResponse(status_code=503, content={"error": detail}, headers={"Retry-After": "60"})
    free_gb = _available_gb()
    if free_gb is not None and free_gb < MIN_FREE_GB:
        logger.warning("refusing: %.1f GB free, need %.1f GB", free_gb, MIN_FREE_GB)
        return JSONResponse(status_code=503, content={"error": f"low memory ({free_gb:.1f} GB free)"},
                            headers={"Retry-After": "60"})
    if not _lock.acquire(blocking=False):  # one image at a time; the caller tries another server or waits
        wait = int(_average_seconds() or 120)
        return JSONResponse(status_code=503, content={"error": "busy"}, headers={"Retry-After": str(wait)})
    try:
        data, started = [], time.monotonic()
        for i in range(body.n):
            seed = (body.seed + i) if body.seed is not None else random.randint(0, 2**32 - 1)
            try:
                image = _state["pipe"](
                    prompt=body.prompt, negative_prompt=body.negative_prompt or DEFAULT_NEGATIVE,
                    width=width, height=height, num_inference_steps=steps, guidance_scale=GUIDANCE,
                    generator=torch.Generator(device="cpu").manual_seed(seed),
                ).images[0]
            except Exception as err:  # noqa: BLE001 - e.g. out of memory: an honest 500
                _state["failed"] += 1
                logger.exception("generation failed")
                raise HTTPException(status_code=500, detail=f"generation failed: {type(err).__name__}") from err
            data.append({"b64_json": _encode(image), "seed": seed})
        seconds = time.monotonic() - started
        _state["made"] += body.n
        _state["recent"].append(seconds / body.n)
        logger.info("made %d image(s) %dx%d, %d steps, %.1fs", body.n, width, height, steps, seconds)
        return {"created": int(time.time()), "data": data,
                "timings": {"seconds": round(seconds, 1), "steps": steps}}
    finally:
        _lock.release()


@app.get("/health")
def health():
    memory = None
    try:
        import psutil

        process = psutil.Process()
        memory = {"process_gb": round(process.memory_info().rss / 1e9, 2),
                  "machine_total_gb": round(psutil.virtual_memory().total / 1e9, 1),
                  "machine_available_gb": round(psutil.virtual_memory().available / 1e9, 1)}
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": _state["pipe"] is not None, "model_dir": MODEL_DIR, "device": _state["device"], "dtype": _state["dtype"],
        "load_seconds": _state["load_seconds"], "busy": _lock.locked(), "images_made": _state["made"],
        "failed": _state["failed"], "average_seconds_per_image": _average_seconds(), "default_steps": DEFAULT_STEPS,
        "output": OUTPUT_FORMAT, "memory": memory, "error": _state["error"],
    }
