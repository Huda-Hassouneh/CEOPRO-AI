"""
KEEL - Automated Marketing System, Background Removal.

Real, working, open-source background removal (rembg - MIT licensed,
https://github.com/danielgatis/rembg, U^2-Net-family segmentation models
run via ONNX Runtime, CPU-only, no API key, no external service call at
inference time). Dispatched by MARKETING_BACKGROUND_REMOVAL_PROVIDER, the
same pattern as image_generation.py's MARKETING_IMAGE_PROVIDER - unset by
default, so nothing changes for an unconfigured deployment.

## Why this is off by default on this platform's own free-tier hosting

Measured directly in this repository's own development sandbox (not on
Render itself, but the same CPU-only, no-GPU constraint applies either
way) before writing this module:

    import rembg                          ->  ~220 MB RSS  (scipy/
                                               scikit-image/pymatting are
                                               real, heavy transitive
                                               dependencies of rembg itself)
    + new_session('u2netp')               ->  ~250 MB RSS  (+23 MB - the
                                               smallest model rembg ships,
                                               4.7 MB on disk)
    + one real background-removal call    ->  ~520-540 MB RSS peak, on
      (400x400 and 1200x1200 test images       both a small and a
       both measured)                          realistic product-photo
                                                 size

That is already at or over Render's free web-service plan's entire 512 MB
RAM budget - in an otherwise-bare Python process, before this service's
own real baseline (torch/transformers/sentence-transformers/faiss, all
already resident in this same process for RAG retrieval and sentiment
classification) is added on top. Enabling MARKETING_BACKGROUND_REMOVAL_PROVIDER=rembg
on the current $0 Render staging deployment risks the whole service being
OOM-killed, not just this one feature failing - so it is never on by
default, and turning it on there is not currently recommended. See
MARKETING_AI_CAPABILITIES.md for the full investigation and the two real
paths to actually enabling it later (a paid Render plan with real RAM
headroom, or running this as a separate process/service).

rembg itself is imported lazily, inside _remove_via_rembg() only - never
at this module's top level - so merely having the dependency installed
(backend/src/ai/requirements.txt) costs nothing until this specific
provider is both configured AND actually invoked.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("CEOPRO_AI_MARKETING_BACKGROUND_REMOVAL")

_NOT_CONFIGURED_MESSAGE = (
    "Background removal is not configured for this environment. "
    "Set MARKETING_BACKGROUND_REMOVAL_PROVIDER to enable it (see MARKETING_AI_CAPABILITIES.md "
    "for why it is off by default on this platform's free-tier hosting)."
)

# The smallest model rembg ships (4.7 MB) - deliberately not the larger,
# more accurate u2net (176 MB) or isnet-general-use (176 MB) - picked to
# keep this feature's own footprint as small as technically possible
# within rembg's own model family, even though (see this module's own
# docstring) even the smallest one still does not fit this platform's
# current free-tier RAM budget.
_REMBG_MODEL = os.getenv("REMBG_MODEL", "u2netp")

_MAX_IMAGE_BYTES = int(os.getenv("MAX_MARKETING_IMAGE_BYTES", str(8 * 1024 * 1024)))


class BackgroundRemovalError(Exception):
    """Raised for every honest non-success outcome. `status` is always one
    of campaigns.background_removal_status's real values - never a fake
    fourth state, and never silently mapped to COMPLETED."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class RemovedBackgroundImage:
    content: bytes
    content_type: str
    provider: str


def _remove_via_rembg(image_bytes: bytes) -> bytes:
    """The one real provider implementation - isolated into its own
    function specifically so tests can patch this exact call site rather
    than needing rembg's real (heavy) model download/inference in every
    test run. Always produces a PNG with an alpha channel (rembg's own
    default output format) - transparency, not a fabricated solid-color
    cutout background."""
    from rembg import new_session, remove  # lazy - see module docstring

    session = new_session(_REMBG_MODEL)
    return remove(image_bytes, session=session)


# Names only (not function references) - remove_background() below calls
# _remove_via_rembg(...) by its plain module-global name rather than
# through a dict of pre-bound callables, specifically so
# unittest.mock.patch("...background_removal._remove_via_rembg", ...) in
# tests actually takes effect: a dict built at import time would have
# already captured the original, unpatched function object.
_KNOWN_PROVIDERS = frozenset({"rembg"})


def remove_background(image_bytes: bytes, provider: Optional[str] = None) -> RemovedBackgroundImage:
    """
    Dispatches to the configured provider (MARKETING_BACKGROUND_REMOVAL_PROVIDER,
    or the explicit `provider` override tests use). Raises
    BackgroundRemovalError for every non-success outcome - this either
    returns a real processed image, or raises; it never returns a
    placeholder/fixture image or silently returns the original unchanged.
    """
    selected = (provider if provider is not None else os.getenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "")).strip().lower()
    if not selected or selected == "none":
        raise BackgroundRemovalError("NOT_CONFIGURED", _NOT_CONFIGURED_MESSAGE)
    if selected not in _KNOWN_PROVIDERS:
        raise BackgroundRemovalError(
            "NOT_CONFIGURED",
            f"MARKETING_BACKGROUND_REMOVAL_PROVIDER={selected!r} is not a recognized provider (expected one of {sorted(_KNOWN_PROVIDERS)}).",
        )

    if not image_bytes:
        raise BackgroundRemovalError("PROVIDER_ERROR", "No source image to remove the background from.")
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise BackgroundRemovalError("PROVIDER_ERROR", f"Source image exceeds the {_MAX_IMAGE_BYTES}-byte limit.")

    logger.info("Removing background via provider=%s", selected)
    try:
        output_bytes = _remove_via_rembg(image_bytes)  # the only known provider today
    except BackgroundRemovalError:
        raise
    except Exception as err:  # noqa: BLE001 - a real, unpredictable third-party model failure (corrupt image, decode error, out-of-memory) must surface as an honest PROVIDER_ERROR, never a 500 with no explanation
        raise BackgroundRemovalError("PROVIDER_ERROR", f"Background removal failed: {err}") from err

    return RemovedBackgroundImage(content=output_bytes, content_type="image/png", provider=selected)


def get_background_removal_capability() -> dict:
    """Read by GET /marketing/options so the frontend can show an honest
    "not configured" state before a tenant ever clicks "Remove
    background" - same convention as image_generation.py's own
    get_image_generation_capability()."""
    selected = os.getenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "").strip().lower()
    if not selected or selected not in _KNOWN_PROVIDERS:
        return {"available": False, "provider": None, "reason": _NOT_CONFIGURED_MESSAGE}
    return {"available": True, "provider": selected, "reason": None}
