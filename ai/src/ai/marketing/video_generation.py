"""
KEEL - Automated Marketing System, AI Video Generation - investigated,
not implemented.

Real conclusion, not a placeholder: video generation cannot be honestly
implemented today without either a paid provider or GPU infrastructure this
platform does not have, so nothing here calls out to a video model. This
module exists only to name the real options investigated and the exact
condition that would make one buildable, so a future pass can add a real
implementation by following marketing/image_generation.py's own provider-
dispatch pattern (one function per provider + one MARKETING_VIDEO_PROVIDER
env var) rather than redesigning anything.

Local/open-source, on this platform's own deployment target (render.yaml's
Render `free` web-service plan - no GPU, a fraction of a CPU core, a few
hundred MB of RAM): ruled out. Every practical open-weight text/image-to-
video model (Stable Video Diffusion, AnimateDiff, CogVideoX, Mochi-1)
needs a CUDA GPU with several GB of VRAM and tens of seconds to minutes of
generation time per clip even on that GPU - there is no CPU-only path that
produces a usable marketing clip in an HTTP request's lifetime, and this
deployment target has no GPU at any price tier this project has approved
using.

External APIs surveyed (Runway Gen-3/Gen-4, Pika, Luma Dream Machine,
Stability AI's image-to-video, Google Veo, Replicate-hosted open video
models): every one of them requires either a paid subscription or a
credit-card-backed pay-per-second/pay-per-generation billing account to
produce a usable clip - none currently offers a real, no-card free tier
comparable to image_generation.py's keyless Pollinations option or Hugging
Face's free-tier Inference API. (A handful of these vendors advertise a
small number of free trial credits at signup, but "trial credits that still
require a credit card on file" does not meet this project's "no credit
card, no paid activation" requirement, so none is treated as viable here.)

Conclusion: video generation is not implemented in this pass. Enabling it
later needs a deliberate paid-vendor decision (approved budget + a credit
card on the account) - it is an infrastructure/business decision, not
something this codebase can close on its own by choosing harder.
"""
from typing import TypedDict


class VideoCapability(TypedDict):
    available: bool
    reason: str
    requirements: list


# The router's GET /marketing/options reads this verbatim into its
# `capabilities.video_generation` field - see this module's own docstring
# for the full investigation behind it. Adding a real provider later means
# replacing this constant with a dispatch function following
# image_generation.generate_campaign_image()'s own pattern, not redesigning
# the router or the campaign workflow around it.
VIDEO_CAPABILITY: VideoCapability = {
    "available": False,
    "reason": (
        "AI video generation is not available. No local/open-source model fits this platform's "
        "GPU-less free-tier deployment target, and every viable external provider requires a paid, "
        "credit-card-backed plan."
    ),
    "requirements": [
        "A paid video-generation provider account (e.g. Runway, Pika, Luma, Stability AI, or a "
        "Replicate-hosted open video model) with billing enabled, or",
        "A GPU-backed deployment target with several GB of free VRAM, replacing the current GPU-less "
        "free-tier hosting, to run an open-weight model locally.",
    ],
}
