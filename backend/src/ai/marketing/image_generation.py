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
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote

import httpx
from PIL import Image

from src.ai.billing import credits

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
    # Providers tried before this one succeeded, with why each failed.
    attempts: List[dict] = field(default_factory=list)


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


def _generate_via_pollinations(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None) -> GeneratedImage:
    url = f"{_POLLINATIONS_BASE_URL}/{quote(prompt)}"
    try:
        response = httpx.get(
            url,
            params={"width": _POLLINATIONS_WIDTH, "height": _POLLINATIONS_HEIGHT, "nologo": "true", "private": "true",
                    "model": os.getenv("POLLINATIONS_MODEL", "flux"), "seed": int(time.time()) % 1_000_000},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Pollinations request failed: {err}") from err

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.status_code == 429:
        raise ProviderBusy("Pollinations rate limit reached", _retry_after(response))
    if response.status_code != 200 or content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
        snippet = response.text[:200] if content_type.startswith("text") or content_type == "application/json" else f"HTTP {response.status_code}"
        raise ImageGenerationError("PROVIDER_ERROR", f"Pollinations did not return an image: {snippet}")

    return GeneratedImage(
        content=response.content, content_type=content_type, provider="pollinations",
        used_reference=False, reference_note=_NO_REFERENCE_SUPPORT_NOTE if reference_image else None,
    )


def _generate_via_huggingface(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None) -> GeneratedImage:
    token = os.getenv("HUGGINGFACE_API_TOKEN")
    if not token:
        raise ImageGenerationError(
            "NOT_CONFIGURED",
            "MARKETING_IMAGE_PROVIDER is 'huggingface' but HUGGINGFACE_API_TOKEN is not set.",
        )
    model = os.getenv("HUGGINGFACE_IMAGE_MODEL", _DEFAULT_HUGGINGFACE_MODEL)
    url = _HUGGINGFACE_API_URL.format(model=model)

    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": prompt},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Hugging Face request failed: {err}") from err

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
        content=response.content, content_type=content_type, provider="huggingface",
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


def _generate_via_cloudflare(prompt: str, reference_image: Optional[bytes] = None, reference_content_type: Optional[str] = None) -> GeneratedImage:
    account, token = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    if not (account and token):
        raise ImageGenerationError("NOT_CONFIGURED", "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are needed for Cloudflare.")
    try:
        response = httpx.post(
            _CLOUDFLARE_URL.format(account=account, model=_CLOUDFLARE_MODEL),
            headers={"Authorization": f"Bearer {token}"}, json={"prompt": prompt[:2048], "steps": 4},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as err:
        raise ImageGenerationError("PROVIDER_ERROR", f"Cloudflare request failed: {type(err).__name__}") from err
    if response.status_code == 429:
        raise ProviderBusy("Cloudflare free allowance or rate limit reached", _retry_after(response))
    try:
        payload = response.json()
        encoded = (payload.get("result") or {}).get("image")
    except ValueError:
        payload, encoded = {}, None
    if response.status_code != 200 or not encoded:
        errors = "; ".join(str(e.get("message", e)) for e in (payload.get("errors") or [])[:2]) if isinstance(payload, dict) else ""
        raise ImageGenerationError("PROVIDER_ERROR", f"Cloudflare did not return an image (HTTP {response.status_code}) {errors}".strip())
    try:
        content = base64.b64decode(encoded)
    except (ValueError, TypeError) as err:
        raise ImageGenerationError("PROVIDER_ERROR", "Cloudflare returned an unreadable image.") from err
    return GeneratedImage(
        content=content, content_type="image/jpeg", provider="cloudflare",
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


_PROVIDERS = {
    "cloudflare": _generate_via_cloudflare,
    "huggingface": _generate_via_huggingface,
    "pollinations": _generate_via_pollinations,
}
_KEYED = {"cloudflare": lambda: bool(os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN")),
          "huggingface": lambda: bool(os.getenv("HUGGINGFACE_API_TOKEN"))}
_TOTAL_BUDGET_SECONDS = float(os.getenv("MARKETING_IMAGE_TOTAL_SECONDS", "120"))
# Spending-policy refusals about one provider (its price, switch or cap):
# the next provider may still be tried.
_PROVIDER_SPECIFIC_REFUSALS = ("COST_NOT_CONFIGURED", "PROVIDER_DISABLED", "PROVIDER_CAP_REACHED")


def provider_chain() -> List[str]:
    """Which providers to try, in order.

    MARKETING_IMAGE_PROVIDERS (comma list) sets it explicitly; the older
    single MARKETING_IMAGE_PROVIDER still works ("none" turns images off).
    Otherwise ("auto"): every free provider with credentials, then the
    keyless Pollinations endpoint unless MARKETING_IMAGE_KEYLESS=false.
    """
    listed = os.getenv("MARKETING_IMAGE_PROVIDERS", "").strip().lower()
    single = os.getenv("MARKETING_IMAGE_PROVIDER", "").strip().lower()
    if listed and listed != "auto":
        names = [n.strip() for n in listed.split(",") if n.strip()]
    elif single and not listed:
        names = [] if single == "none" else [single]
    else:
        names = [name for name, has_key in _KEYED.items() if has_key()]
        if os.getenv("MARKETING_IMAGE_KEYLESS", "true").strip().lower() not in ("0", "false", "no"):
            names.append("pollinations")
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
) -> GeneratedImage:
    """
    Tries each provider in provider_chain() (or only `provider`, which tests
    use) until one returns a real image, within MARKETING_IMAGE_TOTAL_SECONDS.
    A provider that fails moves on to the next; one that is rate limited or
    out of its free allowance is also set aside for its Retry-After. Returns
    real image bytes (checked to be an image) or raises
    ImageGenerationError - never a placeholder.
    """
    names = [provider.strip().lower()] if provider is not None else provider_chain()
    if not names:
        raise ImageGenerationError("NOT_CONFIGURED", _NOT_CONFIGURED_MESSAGE)
    unknown = [n for n in names if n not in _PROVIDERS]
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
            # Paid from the company's AI Credits; an image the provider
            # returned is billed even if it then fails our checks.
            with credits.provider_call(credits.AI, name, "image_generation", {"image": 1}) as call:
                raw = _PROVIDERS[name](prompt, reference_image=reference_image, reference_content_type=reference_content_type)
                call.measured({"image": 1})
            image = verify_image(raw)
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
    are outside services; product photos are never sent)."""
    names = [n for n in provider_chain() if n in _PROVIDERS and (n not in _KEYED or _KEYED[n]())]
    if not names:
        return {"available": False, "provider": None, "providers": [], "external": False, "reason": _NOT_CONFIGURED_MESSAGE}
    return {"available": True, "provider": names[0], "providers": names, "external": True, "reason": None}
