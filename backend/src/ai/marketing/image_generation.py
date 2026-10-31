"""
KEEL - Automated Marketing System, AI Image Generation (Phase 2).

No image-generation model or provider existed anywhere in this repo before
this module (confirmed repo-wide: no diffusers/torch-image pipeline, no
Stability/Replicate/OpenAI image client). This is the first one, and it is
built as a swappable provider behind one env var - MARKETING_IMAGE_PROVIDER
- for the same reason src/ai/rag/llm_client.py keeps its own provider
selection in one file: so a vendor decision later means changing this one
module, not the router or the campaign workflow around it.

Why no locally-run diffusion model: this service's own deployment target
(render.yaml) is Render's `free` web-service plan - no GPU, a fraction of a
CPU core, and a few hundred MB of RAM shared with the whole FastAPI
process. Even a small (SDXL-Turbo/SD-1.5-class) diffusion model needs
several GB of RAM just to load its weights, before a single inference step
- it would not start, let alone generate, on this deployment target. A
hosted HTTP API is therefore the only architecture that can produce a real
image from this service without a paid GPU host.

Three free providers are implemented and tried in order (provider_chain()),
moving to the next whenever one fails, is rate limited or has used its
free allowance (that one is then set aside until its Retry-After):

- "cloudflare": Workers AI's FLUX.1 [schnell] on Cloudflare's free plan
  (a daily free allowance, no card). Needs CLOUDFLARE_ACCOUNT_ID and
  CLOUDFLARE_API_TOKEN. The most dependable free option.
- "huggingface": Hugging Face Inference with a free account token
  (HUGGINGFACE_API_TOKEN); the free monthly credit covers only a few dozen
  images.
- "pollinations": image.pollinations.ai - public and keyless, so it is the
  last resort that works with no setup at all; no service guarantee. On
  by default; MARKETING_IMAGE_KEYLESS=false turns it off.

What leaves KEEL: only the image prompt (the product's name and the
campaign's visual brief - text written to be published). Product photos
are never sent to any provider; the Studio says this before generating.
Every image returned is decoded and size-checked before it is kept, so an
error page served as an image is never shown as a result. Images are
never faked: when no provider produces one, the result says so.

Not run locally: a diffusion model needs several GB of memory and minutes
per image on CPU, which the free hosting (512 MB, a fraction of a core)
cannot do; on a 4-core Codespace SD-Turbo-class models would take tens of
seconds per image plus a multi-GB download - possible for experiments,
not a product default.

A self-hosted server ("local", LOCAL_IMAGE_BASE_URL) is supported for an
operator who does have such hardware: an OpenAI-compatible images API or
AUTOMATIC1111's txt2img API. It is tried first when set, because it is free
per image and the prompt stays on that machine.

Formats (IMAGE_FORMATS): square, 4:5 portrait, 9:16 story, 16:9 landscape
and 1.91:1 link/ad. Each provider is asked for that shape where its API
allows, and every result is centre-cropped to the exact ratio.

This sandbox's network policy blocks every image provider and the model
download CDN, so live generation could not be checked here; the request
building, response parsing, fallback and checks are tested against the
providers' documented response shapes.

## Reference/product image ("product-preservation") generation

`generate_campaign_image()` accepts an optional `reference_image` (an
uploaded/background-removed product photo, from
marketing/background_removal.py's own output or the tenant's raw upload) -
but neither provider implemented here actually uses it. Investigated and
deliberately NOT wired to either provider's real generation call, because
neither has a free-tier contract this module's author could verify well
enough to trust:

- Pollinations' plain keyless `image.pollinations.ai/prompt/...` endpoint
  used here is text-to-image only - it has no documented, reliable
  reference-image/image-editing parameter on the free path this module
  integrates with.
- Hugging Face's *serverless* free Inference API is inconsistent about
  which models/tasks it actually serves for free at any given time; a real
  "image-to-image" task exists in principle on HF's platform, but whether
  a genuinely free (no Inference Endpoint, no paid plan) model actually
  serves it today was not verified from this sandbox (network blocked -
  same limitation as above) and was judged too uncertain to wire up and
  claim working.

Silently accepting a reference image and generating from text alone while
implying the product was preserved is exactly the "fake implementation"
this feature must never be - see get_reference_image_capability() and
GeneratedImage.used_reference/reference_note below: when a reference image
is passed in, the result always says plainly whether it was actually used,
never just "generated: true".
"""
import base64
import io
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote

import httpx
from PIL import Image

from src.ai.billing import credits
from src.ai.core.env_secret import secret

logger = logging.getLogger("CEOPRO_AI_MARKETING_IMAGE")

_NOT_CONFIGURED_MESSAGE = (
    "AI image generation is not configured for this environment. "
    "AI image generation is not configured: every image provider is turned off "
    "(MARKETING_IMAGE_PROVIDERS=none, or MARKETING_IMAGE_KEYLESS=false with no provider keys)."
)

# image.pollinations.ai - keyless, free, no account. See this module's own
# docstring for exactly what "free" means here and its tradeoffs.
_POLLINATIONS_BASE_URL = os.getenv("POLLINATIONS_BASE_URL", "https://image.pollinations.ai/prompt")
_POLLINATIONS_WIDTH = int(os.getenv("MARKETING_IMAGE_WIDTH", "1024"))
_POLLINATIONS_HEIGHT = int(os.getenv("MARKETING_IMAGE_HEIGHT", "1024"))

# Hugging Face's hosted serverless Inference API. FLUX.1-schnell is a
# genuinely open-weight (Apache 2.0), fast (built for few-step inference)
# model - a reasonable free-tier-friendly default, override via
# HUGGINGFACE_IMAGE_MODEL if the configured token's account has a
# different model available on its plan.
# api-inference.huggingface.co is Hugging Face's retired serverless endpoint;
# the HF Inference provider is served through the Inference Providers router.
# Overridable (HUGGINGFACE_INFERENCE_URL) to use another provider route.
_HUGGINGFACE_API_URL = os.getenv(
    "HUGGINGFACE_INFERENCE_URL", "https://router.huggingface.co/hf-inference/models/{model}"
)
_DEFAULT_HUGGINGFACE_MODEL = "black-forest-labs/FLUX.1-schnell"

_TIMEOUT_SECONDS = float(os.getenv("MARKETING_IMAGE_TIMEOUT_SECONDS", "60"))
_MAX_PROMPT_CHARS = 2000

_SUPPORTED_IMAGE_CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp")


# Formats a campaign image can be made in. width/height is what is asked of
# a provider (about one megapixel, sizes most diffusion models accept);
# whatever comes back is centre-cropped to the exact ratio (fit_to_format),
# since not every provider honours a requested size (Workers AI's FLUX.1
# [schnell] always answers 1024x1024). "poster" is the designed fallback's
# size - the platforms' own recommended pixel sizes.
IMAGE_FORMATS = {
    "SQUARE": {"ratio": "1:1", "width": 1024, "height": 1024, "poster": (1080, 1080),
               "channels": ["INSTAGRAM", "FACEBOOK"]},
    "PORTRAIT": {"ratio": "4:5", "width": 896, "height": 1120, "poster": (1080, 1350),
                 "channels": ["INSTAGRAM", "FACEBOOK"]},
    "STORY": {"ratio": "9:16", "width": 768, "height": 1344, "poster": (1080, 1920),
              "channels": ["INSTAGRAM", "TIKTOK", "FACEBOOK"]},
    "LANDSCAPE": {"ratio": "16:9", "width": 1344, "height": 768, "poster": (1920, 1080),
                  "channels": ["FACEBOOK", "GOOGLE_ADS", "WEBSITE"]},
    "WIDE": {"ratio": "1.91:1", "width": 1344, "height": 704, "poster": (1200, 628),
             "channels": ["FACEBOOK", "GOOGLE_ADS", "WEBSITE"]},
}
DEFAULT_IMAGE_FORMAT = "SQUARE"


def _ratio(image_format: str) -> float:
    left, _, right = IMAGE_FORMATS[image_format]["ratio"].partition(":")
    return float(left) / float(right)


def image_formats() -> List[dict]:
    """For GET /marketing/options: the formats the Studio offers."""
    return [{"key": key, "ratio": spec["ratio"], "width": spec["poster"][0], "height": spec["poster"][1],
             "channels": list(spec["channels"])} for key, spec in IMAGE_FORMATS.items()]


def request_size(image_format: Optional[str]) -> tuple:
    spec = IMAGE_FORMATS.get(image_format or DEFAULT_IMAGE_FORMAT, IMAGE_FORMATS[DEFAULT_IMAGE_FORMAT])
    return spec["width"], spec["height"]


class ImageGenerationError(Exception):
    """Raised for every honest non-success outcome. `status` is always one
    of the campaigns.image_generation_status values the migration/router
    persist verbatim - callers must never invent a fourth status or map
    this to a fake "COMPLETED"."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class GeneratedImage:
    content: bytes
    content_type: str
    provider: str
    # True only if the provider actually consumed reference_image to
    # influence the result - false whenever no reference was passed, AND
    # whenever one was passed but the provider ignored it (see this
    # module's own docstring for exactly why that is true of both
    # providers implemented today). reference_note is set whenever a
    # reference image was provided but used_reference is false, explaining
    # why in plain language the frontend can show directly.
    used_reference: bool = False
    reference_note: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # "ai" for a provider-generated image, "designed" for the local fallback poster.
    mode: str = "ai"
    # Providers tried before this one succeeded, with why each failed.
    attempts: List[dict] = field(default_factory=list)
    # The provider's model, when it names one (stored for operators only).
    model: Optional[str] = None
    image_format: str = DEFAULT_IMAGE_FORMAT


def build_image_prompt(campaign: dict) -> str:
    """
    Composes the image prompt entirely from this campaign's own already-
    real fields - never a second LLM call, never new invented details.
    creative_direction (content_generator.py's own structured visual brief
    - product + positioning + theme + strategy, already synthesized for
    exactly this future step) is the core of it; campaign_brief adds the
    concrete product identity back in, since creative_direction is mood/
    composition-focused and may not repeat the product name.

    creative_direction always ends with the literal sentence "No image or
    video has been generated from this brief yet." (content_generator.py's
    _SYSTEM_PROMPT) - stripped here since it is an instruction to a human
    reader, not part of the visual description an image model should draw.
    """
    if (campaign.get("image_prompt") or "").strip():
        # Written in English with the copy for exactly this (see content_generator.py).
        return campaign["image_prompt"].strip()[:_MAX_PROMPT_CHARS]
    direction = (campaign.get("creative_direction") or "").replace(
        "No image or video has been generated from this brief yet.", "",
    ).strip()
    brief = (campaign.get("campaign_brief") or "").strip()

    parts = [p for p in (brief, direction) if p]
    prompt = ". ".join(parts) if parts else "A professional product advertisement photo."
    return prompt[:_MAX_PROMPT_CHARS]


_NO_REFERENCE_SUPPORT_NOTE = (
    "A product reference image was provided, but this provider does not support reference-image "
    "generation - this image was generated from the text brief only, not from your uploaded photo. "
    "See MARKETING_AI_CAPABILITIES.md for why."
)


def _csv(*names: str) -> List[str]:
    """Comma-separated credentials from the first env var that is set."""
    for name in names:
        values = [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]
        if values:
            return values
    return []


def _credentials(name: str) -> List[Optional[str]]:
    """Every account for a provider. Each extra FREE account adds its own
    free daily allowance, which is how the free tiers are stretched; the
    older single-account variables keep working. Pollinations and AI Horde
    also work with no key at all (None)."""
    if name == "huggingface":
        return _csv("HUGGINGFACE_API_TOKENS", "HUGGINGFACE_API_TOKEN")
    if name == "cloudflare":
        pairs = _csv("CLOUDFLARE_ACCOUNTS")
        if not pairs and os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"):
            pairs = [f"{os.environ['CLOUDFLARE_ACCOUNT_ID']}:{os.environ['CLOUDFLARE_API_TOKEN']}"]
        return pairs
    if name == "together":
        return _csv("TOGETHER_API_KEYS")
    if name == "gemini":
        return _csv("GEMINI_API_KEYS")
    if name == "pollinations":
        # Keyed only: the keyless tier stamps a visible "pollinations.ai"
        # watermark on every image (verified live 2026-10-17), which would
        # both expose the provider and ship a watermarked ad.
        return _csv("POLLINATIONS_API_KEYS")
    if name == "aihorde":
        return _csv("HORDE_API_KEYS") or [_ANON_HORDE_KEY]
    if name == "local":  # one "credential" per self-hosted server: its URL
        return _local_image_base_urls()
    return []


def _generate_via_pollinations(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    url = f"{_POLLINATIONS_BASE_URL}/{quote(prompt)}"
    width, height = size or (_POLLINATIONS_WIDTH, _POLLINATIONS_HEIGHT)
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {credential}"} if credential else None,
            params={"width": width, "height": height, "nologo": "true", "private": "true",
                    "model": os.getenv("POLLINATIONS_MODEL", "flux"), "seed": int(time.time()) % 1_000_000},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Pollinations request failed: {err}") from err

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status_code in (402, 429):  # keyless tier closed/limited (402 seen live 2026-10-17)
        raise ProviderBusy(f"Pollinations free tier unavailable (HTTP {response.status_code})", max(_retry_after(response), 900.0))
    if response.status_code != 200 or content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
        snippet = response.text[:200] if content_type.startswith("text") or content_type == "application/json" else f"HTTP {response.status_code}"
        raise ImageGenerationError("PROVIDER_ERROR", f"Pollinations did not return an image: {snippet}")

    return GeneratedImage(
        content=response.content, content_type=content_type, provider="pollinations",
        model=os.getenv("POLLINATIONS_MODEL", "flux"), used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


def _generate_via_huggingface(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    token = credential or secret("HUGGINGFACE_API_TOKEN")
    if not token:
        raise ImageGenerationError(
            "NOT_CONFIGURED",
            "MARKETING_IMAGE_PROVIDER is 'huggingface' but HUGGINGFACE_API_TOKEN is not set.",
        )
    models = _csv("HUGGINGFACE_IMAGE_MODELS", "HUGGINGFACE_IMAGE_MODEL") or [_DEFAULT_HUGGINGFACE_MODEL, "stabilityai/stable-diffusion-xl-base-1.0"]  # both commercially usable licences
    response = None
    for model in models:  # the next model is tried if one is unavailable; a quota error stops (shared credit)
        try:
            response = httpx.post(
                _HUGGINGFACE_API_URL.format(model=model),
                headers={"Authorization": f"Bearer {token}"},
                json={"inputs": prompt, **({"parameters": {"width": size[0], "height": size[1]}} if size else {})},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as err:
            if model == models[-1]:
                raise ImageGenerationError("PROVIDER_ERROR", f"Hugging Face request failed: {type(err).__name__}") from err
            continue
        if response.status_code in (402, 429) or response.status_code == 200 or model == models[-1]:
            break

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status_code in (402, 429):  # free monthly credit used up, or rate limited
        raise ProviderBusy(f"Hugging Face free allowance or rate limit reached (HTTP {response.status_code})", _retry_after(response))
    if response.status_code != 200 or content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
        # A non-image response is almost always HF's own JSON error body -
        # e.g. {"error": "Model is currently loading", "estimated_time": 20}
        # - surfaced verbatim (truncated) rather than a generic message, so
        # a real operator can tell "model cold-starting, retry" apart from
        # "wrong model id" or "invalid token" at a glance.
        raise ImageGenerationError("PROVIDER_ERROR", f"Hugging Face did not return an image (HTTP {response.status_code}): {response.text[:200]}")

    return GeneratedImage(
        content=response.content, content_type=content_type, provider="huggingface", model=model,
        used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


# Cloudflare Workers AI: FLUX.1 [schnell] on Cloudflare's free plan (a
# daily allowance of free "neurons", no card needed; more than the free
# allowance needs the paid Workers plan, which is never switched on here).
# Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (a token with the
# "Workers AI" permission).
_CLOUDFLARE_URL = os.getenv(
    "CLOUDFLARE_AI_URL", "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",
)
_CLOUDFLARE_MODEL = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")


# Tried in order within one account if a model fails (best quality first). All are on
# Workers AI's free allowance, which is shared per ACCOUNT, not per model.
_CLOUDFLARE_MODELS = (
    "@cf/black-forest-labs/flux-1-schnell",
    "@cf/bytedance/stable-diffusion-xl-lightning",
    "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "@cf/lykon/dreamshaper-8-lcm",
)


def _cloudflare_models() -> List[str]:
    return _csv("CLOUDFLARE_IMAGE_MODELS", "CLOUDFLARE_IMAGE_MODEL") or list(_CLOUDFLARE_MODELS)


def _generate_via_cloudflare(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    if credential:
        account, _, token = credential.partition(":")
    else:
        account, token = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    if not (account and token):
        raise ImageGenerationError("NOT_CONFIGURED", "CLOUDFLARE_ACCOUNTS (account_id:token) is needed for Cloudflare.")
    last_error = None
    for model in _cloudflare_models():  # the next model is tried if one fails; a quota error stops (same account allowance)
        body = {"prompt": prompt[:2048]}
        # FLUX.1 [schnell] on Workers AI takes no size (always 1024x1024; cropped afterwards).
        width, height = size or (1024, 1024)
        body.update({"steps": 4} if "flux" in model else {"num_steps": 8, "width": width, "height": height})
        try:
            response = httpx.post(
                _CLOUDFLARE_URL.format(account=account, model=model),
                headers={"Authorization": f"Bearer {token}"}, json=body, timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as err:
            last_error = ImageGenerationError("PROVIDER_ERROR", f"Cloudflare request failed: {type(err).__name__}")
            continue
        if response.status_code in (402, 429):
            raise ProviderBusy("Cloudflare free allowance or rate limit reached", _retry_after(response))
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if response.status_code == 200 and content_type in _SUPPORTED_IMAGE_CONTENT_TYPES:
            content = response.content  # SDXL-class models answer with raw image bytes
        else:
            try:
                payload = response.json()
                encoded = (payload.get("result") or {}).get("image")
                content = base64.b64decode(encoded) if response.status_code == 200 and encoded else None
            except (ValueError, TypeError, AttributeError):
                payload, content = {}, None
            if not content:
                errors = "; ".join(str(e.get("message", e)) for e in (payload.get("errors") or [])[:2]) if isinstance(payload, dict) else ""
                last_error = ImageGenerationError("PROVIDER_ERROR", f"Cloudflare did not return an image (HTTP {response.status_code}) {errors}".strip())
                continue
            content_type = "image/jpeg"
        return GeneratedImage(
            content=content, content_type=content_type, provider="cloudflare", model=model,
            used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
        )
    raise last_error or ImageGenerationError("PROVIDER_ERROR", "Cloudflare returned no image.")


_GEMINI_URL = os.getenv("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent")


_GEMINI_RATIOS = {"1:1": 1.0, "4:5": 0.8, "9:16": 9 / 16, "16:9": 16 / 9, "3:4": 0.75, "4:3": 4 / 3}


def _generate_via_gemini(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    """Google AI Studio's image model on a free API key (no card). Images carry
    Google's invisible SynthID mark, never a visible one."""
    if not credential:
        raise ImageGenerationError("NOT_CONFIGURED", "GEMINI_API_KEYS is not set.")
    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    try:
        response = httpx.post(
            _GEMINI_URL.format(model=model), headers={"x-goog-api-key": credential},
            json={"contents": [{"parts": [{"text": prompt[:1500]}]}], "generationConfig": {
                "responseModalities": ["IMAGE"],
                **({"imageConfig": {"aspectRatio": min(_GEMINI_RATIOS, key=lambda r: abs(_GEMINI_RATIOS[r] - size[0] / size[1]))}}
                   if size else {})}},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Gemini request failed: {type(err).__name__}") from err
    if response.status_code in (402, 429):
        raise ProviderBusy(f"Gemini free allowance or rate limit reached (HTTP {response.status_code})", _retry_after(response))
    try:
        parts = response.json()["candidates"][0]["content"]["parts"]
        inline = next(p["inlineData"] for p in parts if "inlineData" in p)
        content, content_type = base64.b64decode(inline["data"]), inline.get("mimeType", "image/png")
    except (ValueError, KeyError, IndexError, TypeError, StopIteration) as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Gemini did not return an image (HTTP {response.status_code}).") from err
    return GeneratedImage(
        content=content, content_type=content_type, provider="gemini", model=model,
        used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


_TOGETHER_URL = os.getenv("TOGETHER_URL", "https://api.together.xyz/v1/images/generations")
_ANON_HORDE_KEY = "0000000000"
_HORDE_URL = "https://aihorde.net/api/v2"
_HORDE_MAX_WAIT = float(os.getenv("MARKETING_AI_HORDE_MAX_WAIT_SECONDS", "240"))


def _generate_via_together(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    """Together's free FLUX.1 [schnell] model (needs a free account key)."""
    if not credential:
        raise ImageGenerationError("NOT_CONFIGURED", "TOGETHER_API_KEYS is not set.")
    try:
        response = httpx.post(
            _TOGETHER_URL, headers={"Authorization": f"Bearer {credential}"},
            json={"model": os.getenv("TOGETHER_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell-Free"),
                  "prompt": prompt[:1500], "width": (size or (1024, 1024))[0], "height": (size or (1024, 1024))[1],
                  "steps": 4, "n": 1,
                  "response_format": "b64_json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Together request failed: {type(err).__name__}") from err
    if response.status_code in (402, 429):
        raise ProviderBusy(f"Together free allowance or rate limit reached (HTTP {response.status_code})", _retry_after(response))
    try:
        content = base64.b64decode(response.json()["data"][0]["b64_json"])
    except (ValueError, KeyError, IndexError, TypeError) as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Together did not return an image (HTTP {response.status_code}).") from err
    return GeneratedImage(
        content=content, content_type="image/png", provider="together",
        used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


def _horde_size(size: Optional[tuple]) -> tuple:
    """The requested shape at about 768x768 pixels in all (what anonymous
    Horde workers accept), each side a multiple of 64 (Horde's rule)."""
    width, height = size or (768, 768)
    scale = (768 * 768 / (width * height)) ** 0.5
    return max(64, int(width * scale) // 64 * 64), max(64, int(height * scale) // 64 * 64)


def _generate_via_aihorde(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    """AI Horde (aihorde.net): a free, community-run Stable Diffusion network.
    Works with no account (the anonymous key) but anonymous jobs can wait in a
    queue for minutes, so it sits last in the chain; a free registered key
    (HORDE_API_KEYS) is served much sooner. Verified live 2026-10-17."""
    headers = {"apikey": credential or _ANON_HORDE_KEY, "Client-Agent": "keel-marketing:1:contact"}
    body = {"prompt": f"{prompt[:1200]} ### text, letters, watermark, logo, blurry, low quality, deformed",
            "nsfw": False, "censor_nsfw": True, "r2": True,
            # Horde rejects sizes that are not multiples of 64 (HTTP 400).
            "params": {"width": _horde_size(size)[0], "height": _horde_size(size)[1], "steps": 25, "n": 1, "cfg_scale": 6}}
    job = None
    try:
        submitted = httpx.post(f"{_HORDE_URL}/generate/async", headers=headers, json=body, timeout=_TIMEOUT_SECONDS)
        if submitted.status_code == 429:
            raise ProviderBusy("AI Horde rate limit reached", _retry_after(submitted))
        if submitted.status_code >= 400:
            raise ImageGenerationError("PROVIDER_ERROR", f"AI Horde rejected the request (HTTP {submitted.status_code}).")
        job = submitted.json().get("id")
        if not job:
            raise ImageGenerationError("PROVIDER_ERROR", "AI Horde returned no job id.")
        deadline = time.monotonic() + _HORDE_MAX_WAIT
        while time.monotonic() < deadline:
            time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
            check = httpx.get(f"{_HORDE_URL}/generate/check/{job}", headers=headers, timeout=_TIMEOUT_SECONDS).json()
            if check.get("faulted"):
                raise ImageGenerationError("PROVIDER_ERROR", "AI Horde job failed.")
            if check.get("done"):
                generations = httpx.get(f"{_HORDE_URL}/generate/status/{job}", headers=headers, timeout=_TIMEOUT_SECONDS).json().get("generations")
                url = (generations or [{}])[0].get("img")
                if not url:
                    raise ImageGenerationError("PROVIDER_ERROR", "AI Horde returned no image.")
                image = httpx.get(url, timeout=_TIMEOUT_SECONDS, follow_redirects=True)
                content_type = image.headers.get("content-type", "").split(";")[0].strip().lower()
                if image.status_code != 200 or content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
                    raise ImageGenerationError("PROVIDER_ERROR", "AI Horde image download failed.")
                return GeneratedImage(
                    content=image.content, content_type=content_type, provider="aihorde",
                    used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
                )
        raise ProviderBusy("AI Horde queue too long", 300.0)
    except (httpx.HTTPError, ValueError) as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"AI Horde request failed: {type(err).__name__}") from err
    finally:
        if job:  # always free the queue slot if we stop waiting
            try:
                httpx.delete(f"{_HORDE_URL}/generate/status/{job}", headers=headers, timeout=10)
            except httpx.HTTPError:
                pass


# A self-hosted image server on the operator's own hardware (free per image,
# and the prompt never leaves that machine). Two widely used local APIs:
#   openai  POST {base}/v1/images/generations, b64_json answer - LocalAI,
#           stable-diffusion.cpp's server and other OpenAI-compatible ones
#   a1111   POST {base}/sdapi/v1/txt2img - AUTOMATIC1111, Forge, SD.Next
# Off until LOCAL_IMAGE_BASE_URL is set. A diffusion model needs a GPU or
# several GB of RAM and tens of seconds per image on CPU, so this is for a
# machine that can run one - never the 512 MB free web service.
_LOCAL_IMAGE_TIMEOUT_SECONDS = float(os.getenv("LOCAL_IMAGE_TIMEOUT_SECONDS", "300"))
_NEGATIVE_PROMPT = "text, letters, watermark, logo, blurry, low quality, deformed"


def _local_image_base_urls() -> List[str]:
    """Every self-hosted server: LOCAL_IMAGE_BASE_URLS (comma list - one per
    machine, each its own chain entry with its own busy/cooldown state) or
    the single LOCAL_IMAGE_BASE_URL."""
    return [u.rstrip("/") for u in _csv("LOCAL_IMAGE_BASE_URLS", "LOCAL_IMAGE_BASE_URL")]


def _local_image_base_url() -> str:
    urls = _local_image_base_urls()
    return urls[0] if urls else ""


def local_server_health(timeout: float = 3.0) -> List[dict]:
    """Each self-hosted server's own /health (device, busy, measured seconds
    per image, memory), for the capacity view. Addresses are not included."""
    report = []
    for i, base in enumerate(_local_image_base_urls(), 1):
        try:
            data = httpx.get(f"{base}/health", timeout=timeout).json()
            report.append({"server": i, "ok": bool(data.get("ok")), "busy": data.get("busy"), "device": data.get("device"),
                           "dtype": data.get("dtype"), "images_made": data.get("images_made"),
                           "average_seconds_per_image": data.get("average_seconds_per_image"),
                           "memory": data.get("memory")})
        except (httpx.HTTPError, ValueError):
            report.append({"server": i, "ok": False})
    return report


def only_self_hosted() -> bool:
    """True when every image provider that can run is a self-hosted server
    (no per-image provider cost)."""
    entries = [e for e in provider_chain() if _split(e)[0] != "local" or _local_image_base_urls()]
    return bool(entries) and all(_split(e)[0] == "local" for e in entries)


def _generate_via_local(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None, credential: Optional[str] = None, size: Optional[tuple] = None, seed: Optional[int] = None) -> GeneratedImage:
    base = (credential or _local_image_base_url()).rstrip("/")
    if not base:
        raise ImageGenerationError("NOT_CONFIGURED", "LOCAL_IMAGE_BASE_URL is not set.")
    api = os.getenv("LOCAL_IMAGE_API", "openai").strip().lower()
    model = os.getenv("LOCAL_IMAGE_MODEL", "").strip() or None
    key = os.getenv("LOCAL_IMAGE_API_KEY", "").strip()
    width, height = size or (1024, 1024)
    if api == "a1111":
        url = f"{base}/sdapi/v1/txt2img"
        body = {"prompt": prompt[:2000], "negative_prompt": _NEGATIVE_PROMPT, "width": width, "height": height,
                "steps": int(os.getenv("LOCAL_IMAGE_STEPS", "20")), "batch_size": 1, "n_iter": 1,
                "seed": seed if seed is not None else -1}
    elif api == "openai":
        url = f"{base}/v1/images/generations"
        body = {"prompt": prompt[:2000], "n": 1, "size": f"{width}x{height}", "response_format": "b64_json",
                **({"model": model} if model else {}), **({"seed": seed} if seed is not None else {})}
    else:
        raise ImageGenerationError("NOT_CONFIGURED", f"LOCAL_IMAGE_API must be 'openai' or 'a1111', not {api!r}.")
    try:
        response = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"} if key else None,
                              timeout=_LOCAL_IMAGE_TIMEOUT_SECONDS)
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Local image server request failed: {type(err).__name__}") from err
    if response.status_code in (429, 503):  # busy with another image
        # Our own server: check back soon rather than sitting out a whole image's time.
        raise ProviderBusy(f"Local image server busy (HTTP {response.status_code})", min(_retry_after(response), 15.0))
    try:
        payload = response.json() if response.status_code == 200 else {}
        encoded = payload["images"][0] if api == "a1111" else payload["data"][0]["b64_json"]
        if "," in encoded[:100] and encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        content = base64.b64decode(encoded)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Local image server did not return an image (HTTP {response.status_code}).") from err
    return GeneratedImage(
        content=content, content_type="image/png", provider="local", model=model or api,
        used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


class ProviderBusy(ImageGenerationError):
    """The provider is rate limited or out of its free allowance right now."""

    def __init__(self, message: str, retry_after: float):
        super().__init__("PROVIDER_ERROR", message)
        self.retry_after = retry_after


def _retry_after(response) -> float:
    try:
        return max(5.0, min(3600.0, float(response.headers.get("retry-after", 60))))
    except (TypeError, ValueError):
        return 60.0


_MIN_IMAGE_SIDE = 256
_RATIO_TOLERANCE = 0.02


def verify_image(image: GeneratedImage) -> GeneratedImage:
    """A provider's bytes are kept only if they really are an image of a
    usable size (an error page served as image/jpeg is not)."""
    try:
        with Image.open(io.BytesIO(image.content)) as picture:
            picture.verify()
        with Image.open(io.BytesIO(image.content)) as picture:
            width, height, kind = picture.width, picture.height, (picture.format or "").lower()
    except Exception as err:  # noqa: BLE001 - PIL raises many kinds for bad bytes
        raise ImageGenerationError("PROVIDER_ERROR", f"{image.provider} returned bytes that are not an image.") from err
    if min(width, height) < _MIN_IMAGE_SIDE:
        raise ImageGenerationError("PROVIDER_ERROR", f"{image.provider} returned a {width}x{height} image, too small to use.")
    image.content_type = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(kind, image.content_type)
    image.width, image.height = width, height
    return image


def fit_to_format(image: GeneratedImage, image_format: str) -> GeneratedImage:
    """Centre-crops a verified image to the format's exact ratio (never
    stretches it, never enlarges it). An image already within 2% of the
    ratio is kept as it is."""
    target = _ratio(image_format)
    image.image_format = image_format
    with Image.open(io.BytesIO(image.content)) as picture:
        picture.load()
        width, height = picture.size
        if abs(width / height - target) / target <= _RATIO_TOLERANCE:
            image.width, image.height = width, height
            return image
        if width / height > target:
            new_width = round(height * target)
            left = (width - new_width) // 2
            box = (left, 0, left + new_width, height)
        else:
            new_height = round(width / target)
            top = (height - new_height) // 2
            box = (0, top, width, top + new_height)
        cropped = picture.crop(box)
        buffer = io.BytesIO()
        if image.content_type == "image/jpeg":
            cropped.convert("RGB").save(buffer, format="JPEG", quality=92)
        else:
            cropped.save(buffer, format="PNG", optimize=True)
            image.content_type = "image/png"
    image.content = buffer.getvalue()
    image.width, image.height = cropped.size
    if min(image.width, image.height) < _MIN_IMAGE_SIDE:
        raise ImageGenerationError("PROVIDER_ERROR", f"{image.provider} image is too small for the {image_format} format.")
    return image


_PROVIDERS = {
    "local": _generate_via_local,
    "cloudflare": _generate_via_cloudflare,
    "huggingface": _generate_via_huggingface,
    "together": _generate_via_together,
    "gemini": _generate_via_gemini,
    "pollinations": _generate_via_pollinations,
    "aihorde": _generate_via_aihorde,
}
_KEYED = {name: (lambda n=name: bool(_credentials(n))) for name in ("cloudflare", "huggingface", "together", "gemini", "pollinations")}
_TOTAL_BUDGET_SECONDS = float(os.getenv("MARKETING_IMAGE_TOTAL_SECONDS", "120"))
# Spending-policy refusals about one provider (its price, switch or cap):
# the next provider may still be tried.
_PROVIDER_SPECIFIC_REFUSALS = ("COST_NOT_CONFIGURED", "PROVIDER_DISABLED", "PROVIDER_CAP_REACHED")

# Entries after the fast, keyed ones - slow or unreliable but needing no account.
_KEYLESS_ORDER = ("aihorde",)


def _entries(name: str) -> List[str]:
    """One chain entry per account: "huggingface#1", "huggingface#2" ... Each
    has its own cooldown, so one exhausted free account never blocks the rest."""
    return [f"{name}#{i}" for i, _ in enumerate(_credentials(name), 1)]


def _split(entry: str):
    name, _, index = entry.partition("#")
    credentials = _credentials(name)
    position = int(index) - 1 if index.isdigit() else 0
    return name, (credentials[position] if position < len(credentials) else None)


def provider_chain() -> List[str]:
    """Which providers/accounts to try, in order.

    MARKETING_IMAGE_PROVIDERS (comma list) sets it explicitly; the older
    single MARKETING_IMAGE_PROVIDER still works ("none" turns images off).
    Otherwise ("auto"): a self-hosted image server first when
    LOCAL_IMAGE_BASE_URL is set (free, and the prompt stays on that
    machine), then every free account with credentials - rotated so the
    load (and free daily allowance) is spread evenly - then the keyless
    fallback (AI Horde) unless MARKETING_IMAGE_KEYLESS=false.
    """
    listed = os.getenv("MARKETING_IMAGE_PROVIDERS", "").strip().lower()
    single = os.getenv("MARKETING_IMAGE_PROVIDER", "").strip().lower()
    if listed and listed != "auto":
        names = [n.strip() for n in listed.split(",") if n.strip()]
    elif single and not listed:
        names = [] if single == "none" else [single]
    else:
        keyed = [entry for name in _KEYED for entry in _entries(name)]
        random.shuffle(keyed)
        names = _entries("local") + keyed
        if os.getenv("MARKETING_IMAGE_KEYLESS", "true").strip().lower() not in ("0", "false", "no"):
            names += list(_KEYLESS_ORDER)
    # A plain "local" means every configured self-hosted server.
    names = [entry for n in names for entry in ((_entries("local") or ["local"]) if n == "local" else [n])]
    return [n for n in dict.fromkeys(names) if n != "none"]


def _cooldown_key(name: str) -> str:
    return f"keel:image-provider-busy:{name}"


def _cooling_down(name: str) -> bool:
    try:
        from src.ai.core.redis_client import get_redis_client

        return bool(get_redis_client().get(_cooldown_key(name)))
    except Exception:  # noqa: BLE001 - no Redis: try every provider
        return False


def _cool_down(name: str, seconds: float) -> None:
    try:
        from src.ai.core.redis_client import get_redis_client

        get_redis_client().setex(_cooldown_key(name), int(seconds), "1")
    except Exception:  # noqa: BLE001
        pass

# Neither provider above actually supports it (see this module's own
# docstring) - a single source of truth the router/capabilities endpoint
# both read, rather than each guessing from GeneratedImage.used_reference
# after the fact.
REFERENCE_IMAGE_CAPABILITY = {
    "available": False,
    "reason": (
        "Reference-image (product-preservation) generation is not available from either implemented "
        "image provider. Pollinations' keyless endpoint is text-to-image only; Hugging Face's free "
        "serverless Inference API does not have a verified free reference-image/image-to-image path for "
        "the configured model. See MARKETING_AI_CAPABILITIES.md for the full investigation."
    ),
}


def get_reference_image_capability() -> dict:
    return dict(REFERENCE_IMAGE_CAPABILITY)


def generate_campaign_image(
    prompt: str, provider: Optional[str] = None,
    reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None,
    image_format: str = DEFAULT_IMAGE_FORMAT, seed: Optional[int] = None,
) -> GeneratedImage:
    """
    Tries each provider in provider_chain() (or only `provider`, which tests
    use) until one returns a real image, within MARKETING_IMAGE_TOTAL_SECONDS.
    A provider that fails moves on to the next; one that is rate limited or
    out of its free allowance is also set aside for its Retry-After. Returns
    real image bytes (checked to be an image) or raises
    ImageGenerationError - never a placeholder. The image is asked for in
    image_format's shape and cropped to its exact ratio (fit_to_format).
    """
    if image_format not in IMAGE_FORMATS:
        raise ImageGenerationError("PROVIDER_ERROR", f"Unknown image format {image_format!r} (expected one of {sorted(IMAGE_FORMATS)}).")
    size = request_size(image_format)
    names = [provider.strip().lower()] if provider is not None else provider_chain()
    if not names:
        raise ImageGenerationError("NOT_CONFIGURED", _NOT_CONFIGURED_MESSAGE)
    unknown = [n for n in names if _split(n)[0] not in _PROVIDERS]
    if unknown:
        raise ImageGenerationError(
            "NOT_CONFIGURED", f"Unknown image provider {unknown[0]!r} (expected one of {sorted(_PROVIDERS)}).",
        )
    if not (prompt or "").strip():
        raise ImageGenerationError("PROVIDER_ERROR", "No creative direction/brief available to build an image prompt from.")

    attempts, started = [], time.monotonic()
    for name in names:
        if provider is None and _cooling_down(name):
            attempts.append({"provider": name, "reason": "busy"})
            continue
        if attempts and time.monotonic() - started > _TOTAL_BUDGET_SECONDS:
            attempts.append({"provider": name, "reason": "out_of_time"})
            break
        logger.info("Generating marketing image via %s (reference_image=%s)", name, bool(reference_image))
        try:
            # Paid from the company's AI Credits (billed per BASE provider, never per
            # account entry); an image the provider returned is billed even if it
            # then fails our checks.
            base, credential = _split(name)
            with credits.provider_call(credits.AI, base, "image_generation", {"image": 1}) as call:
                raw = _PROVIDERS[base](
                    prompt, reference_image=reference_image, reference_content_type=reference_content_type,
                    credential=credential, size=size, seed=seed,
                )
                call.measured({"image": 1})
            image = fit_to_format(verify_image(raw), image_format)
        except credits.BudgetError as err:
            if err.reason not in _PROVIDER_SPECIFIC_REFUSALS:
                raise  # the company's budget or access: no other provider may run either
            attempts.append({"provider": name, "reason": "not_configured"})
            logger.warning("image provider %s refused by spending policy: %s", name, err.reason)
            continue
        except ProviderBusy as err:
            _cool_down(name, err.retry_after)
            attempts.append({"provider": name, "reason": "busy"})
            logger.warning("image provider %s busy: %s", name, err.message)
            continue
        except ImageGenerationError as err:
            attempts.append({"provider": name, "reason": "not_configured" if err.status == "NOT_CONFIGURED" else "failed"})
            logger.warning("image provider %s failed: %s", name, err.message)
            if len(names) == 1:  # nothing to fall back to: keep the provider's own explanation
                err.attempts = attempts
                raise
            continue
        image.attempts = attempts
        return image
    if all(a["reason"] == "not_configured" for a in attempts):
        raise ImageGenerationError("NOT_CONFIGURED", _NOT_CONFIGURED_MESSAGE)
    summary = ", ".join(f"{a['provider']}: {a['reason']}" for a in attempts)
    error = ImageGenerationError("PROVIDER_ERROR", f"No image provider produced an image ({summary}).")
    error.attempts = attempts
    raise error


def get_image_generation_capability() -> dict:
    """Read by GET /marketing/options so the frontend shows an honest state
    before anyone clicks: whether images can be made, and whether that
    sends the campaign's text to an outside service (all current providers
    are outside services; product photos are never sent). Which provider
    serves an image is deliberately not exposed - only server logs name it."""
    def usable(entry: str) -> bool:
        base, credential = _split(entry)
        if base == "local":
            return bool(_local_image_base_urls())
        return base not in _KEYED or credential is not None

    usable_entries = [entry for entry in provider_chain() if usable(entry)]
    if not usable_entries:
        return {"available": False, "provider": None, "providers": [], "external": False, "reason": _NOT_CONFIGURED_MESSAGE}
    # "external": the prompt may go to an outside service (any provider but a self-hosted one).
    external = any(_split(entry)[0] != "local" for entry in usable_entries)
    return {"available": True, "provider": "ai", "providers": ["ai"], "external": external, "reason": None}
