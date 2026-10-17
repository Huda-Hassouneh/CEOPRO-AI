# Automated Marketing System - AI Image/Video Capabilities

What's actually implemented, what was investigated and ruled out, and
exactly why - written so nobody has to re-derive this investigation later.
Nothing in this document should be read as "this works, trust it blindly" -
see each section's own "Verified" note for exactly what was and wasn't
checked, and how.

## 1. AI image generation - implemented, provider-configurable, off by default

`src/ai/marketing/image_generation.py` calls a real external image-
generation API and returns real generated image bytes - there is no local
model, no fixture image, and no code path that returns a placeholder
labeled as a real generation. `MARKETING_IMAGE_PROVIDER` selects the
provider; leaving it unset (the default, including on the current Render
staging deployment) makes `POST /marketing/campaigns/{id}/generate-image`
honestly report `image_generation_status: "NOT_CONFIGURED"` instead of
attempting anything.

### Why not a locally-run model

This service's real deployment target (`render.yaml`) is Render's `free`
web-service plan: no GPU, a fraction of a CPU core, a few hundred MB of RAM
shared with the whole FastAPI process. Even the smallest practical
diffusion models (SD-1.5, SDXL-Turbo) need several GB of RAM just to load
their weights, before a single inference step - this deployment target
cannot run one at all, at any image size, let alone generate anything in
an HTTP request's lifetime. A hosted HTTP API is therefore the only
architecture that can produce a real image from this service without a
paid GPU host.

### Providers implemented

| Provider | API availability | Free/open-source | API key required | Credit card required | Cost | GPU/RAM/storage on this service | Compatible with current architecture | Compatible with free Render staging |
|---|---|---|---|---|---|---|---|---|
| **Pollinations** (`image.pollinations.ai`) | Yes - public HTTP GET, no auth | Yes - keyless, no account | No | No | $0 | None (remote HTTP call only) | Yes - one `httpx.get()` call | Yes |
| **Hugging Face Inference API** | Yes - hosted serverless inference | Free tier (account required); model availability on the free tier changes over time - verify before depending on it | Yes (`HUGGINGFACE_API_TOKEN`) | No (to create the account/token itself) | $0 on the free tier, as long as the configured model stays on it | None (remote HTTP call only) | Yes - one `httpx.post()` call | Yes |

Both were chosen specifically because they satisfy every constraint this
feature was built under: no paid activation, no credit card, no silent
billing risk. Pollinations needs zero setup at all (no env var but
`MARKETING_IMAGE_PROVIDER=pollinations`); Hugging Face needs a free account
+ token but offers a documented, swappable model catalog.

Providers considered and ruled out (all require a paid/credit-card-backed
plan for real, production-quality usage): OpenAI (DALL-E/gpt-image),
Stability AI's API, Replicate (pay-per-use), Google's Imagen. None is
implemented here.

### What the image prompt is built from

`image_generation.build_image_prompt()` composes the prompt entirely from
the campaign's own already-real fields - `campaign_brief` (product
identity) + `creative_direction` (the LLM-synthesized visual brief that
already folds in product understanding, market positioning, the chosen
visual theme, and any custom creative prompt - see
`content_generator.py`'s own docstring). No second LLM call, no invented
detail beyond what the campaign itself already established.

### Uploaded source image is still not analyzed

An uploaded source/reference product image (`POST
/marketing/campaigns/{id}/image`) is still storage-only by itself - it is
**not** sent to either image-generation provider and does not influence
the generated image at all. Neither Pollinations nor the default Hugging
Face model (FLUX.1-schnell) accepts an input image (both are text-to-image
only); wiring a genuinely image-conditioned/image-to-image provider in is
a real future change to `image_generation.py`; this pass does not claim
that capability exists.

## 1a. Product reference image workflow - background removal implemented, reference-conditioned generation is not

A tenant can now upload a product photo, remove its background (a real,
separate processing step - see below), preview either version, and mark
one as this campaign's "reference image" (`POST
/marketing/campaigns/{id}/reference-selection`). The original upload is
never modified or deleted by any of this - background removal always
writes a second, separate stored image.

**What this does NOT do**: neither `generate_campaign_image()` provider
implemented today (Pollinations, Hugging Face's default text-to-image
model) actually consumes that reference image to influence the generated
result - see section 1's "Reference/product image" note in
`image_generation.py`'s own docstring for exactly why (no free-tier
contract for either provider could be verified reliably enough to trust).
The reference image *is* read from storage and passed through the
function signature (`generate_campaign_image(..., reference_image=...)`),
proving the plumbing is real and ready - but `GeneratedImage.used_reference`
is always `false` for both providers today, and the API/UI both say so
explicitly (`image_generation_used_reference` / `image_generation_reference_note`)
rather than silently generating from text alone while implying the
product photo was used. This is the single most important honesty
constraint in this part of the feature: a reference selection existing
does not by itself mean the generated image reflects the product photo.

### Background removal - real, working, off by default

`src/ai/marketing/background_removal.py` uses **rembg** (MIT-licensed,
open-source, https://github.com/danielgatis/rembg) - a real U^2-Net-family
segmentation model run locally via ONNX Runtime, CPU-only, no API key, no
external network call at inference time (only a one-time ~4.7MB model
download from GitHub on first use, cached to disk after). Dispatched by
`MARKETING_BACKGROUND_REMOVAL_PROVIDER`, unset (and therefore
`NOT_CONFIGURED`) by default.

| Requirement | Pollinations/HF comparison | rembg |
|---|---|---|
| Free/open-source | Yes | Yes (MIT) |
| API key required | No / Yes | No |
| Credit card required | No | No |
| Cost | $0 | $0 |
| Network call at inference time | Yes (remote API) | No (fully local after first model download) |
| GPU/RAM/storage on this service | None (remote call) | **Real, measured, significant** - see below |
| Compatible with free Render staging | Yes | **No - see below** |

**Why this is off by default on Render's free plan**: measured directly
in this repository's own development sandbox before writing this module
(same CPU-only, no-GPU constraint as Render's free plan either way):

```
import rembg                          ->  ~220 MB RSS  (scipy/scikit-image/
                                           pymatting are real, heavy
                                           transitive dependencies of rembg
                                           itself, not something this
                                           module chose to add)
+ new_session('u2netp')               ->  ~250 MB RSS  (+23 MB - the
                                           smallest model rembg ships,
                                           4.7 MB on disk; larger models
                                           like the default u2net are
                                           176 MB and would cost more)
+ one real background-removal call    ->  ~520-540 MB RSS peak, on both a
  (400x400 and 1200x1200 test images       400x400 and a 1200x1200
   both measured)                          synthetic product image
```

That is already at or over Render's free web-service plan's **entire**
512 MB RAM budget, in an otherwise-bare Python process - before this
service's own real baseline (torch/transformers/sentence-transformers/
faiss, all already resident in this same process for RAG retrieval and
sentiment classification) is added on top. Enabling
`MARKETING_BACKGROUND_REMOVAL_PROVIDER=rembg` on the current $0 Render
staging deployment risks the **whole service** being OOM-killed, not just
this one feature failing.

**Real paths to enabling it later** (per the "document the limitation and
use the best practical architecture that does not break staging"
instruction this was built under): (a) upgrade the `ai` service's Render
plan to one with real RAM headroom (a paid decision, not made here), or
(b) run background removal as a separate, smaller process/service with
its own memory budget - Render's free tier has no Background Worker
service type at all (see `render.yaml`'s own note on this same
constraint for the market-scraper workers), so this also implies either a
paid Render service or self-hosting it elsewhere. Neither is implemented
here without explicit approval, per the cost-control instructions this
feature was built under.

**Free remote alternatives considered**: remove.bg and similar hosted
background-removal APIs were considered and rejected - their free tiers
are one-time trial credits (not a genuinely recurring free allowance) and
still require an account; none offers a Pollinations-style unlimited
keyless free tier. rembg remains the only option that is genuinely,
unconditionally free with no account/card/credits - its cost is RAM, not
money.

### Verified

Unlike the image-generation providers, **rembg's real background-removal
model was actually installed and run in this development sandbox** -
`tests/test_marketing_background_removal.py::test_remove_background_rembg_real_integration`
calls the real model (not mocked) against a real synthetic image and
passed, producing a genuine RGBA (transparent) PNG output. This is the one
part of this entire feature that was verified end-to-end for real, not
just at the request/response-shape level - because rembg's model
downloads from GitHub, which (unlike arbitrary third-party hosts) this
development sandbox's network policy allows. The measured memory numbers
above come from that same verified run.

### Honest states, not fake success

`campaigns.image_generation_status` is always one of `COMPLETED` /
`NOT_CONFIGURED` / `PROVIDER_ERROR` - a provider network failure, an
invalid/expired token, a cold-starting Hugging Face model, or no provider
configured at all are all surfaced as their real status with the real
error text, never silently mapped to `COMPLETED`. The frontend renders
each state distinctly (generating / generated / not configured / provider
error) - see `CampaignResultsView.jsx`.

### Verified

This module's own request-building, response-parsing, and error-mapping
logic is covered by `tests/test_marketing_image_generation.py`, with the
HTTP boundary (`httpx.get`/`httpx.post`) mocked. **A real, live end-to-end
call to either provider was not verified from the development sandbox this
feature was built in** - that sandbox's own outbound network policy
blocks arbitrary third-party hosts (`image.pollinations.ai` and
`huggingface.co` were both refused at the egress proxy during
development). Verify a real call against whichever provider is configured
- from the Render staging deployment, or a local dev machine with normal
internet access - before relying on this in production.

## 2. AI video generation - investigated, not implemented

No video is generated anywhere in this codebase, and nothing pretends to.
`src/ai/marketing/video_generation.py` documents the investigation and
exposes a static `VIDEO_CAPABILITY` the frontend reads via `GET
/marketing/options`'s `capabilities.video_generation` - `available: false`
with the real reason and requirements, not a hidden/disabled button that
implies "coming soon" with no explanation.

### Local/open-source - ruled out

Every practical open-weight text/image-to-video model (Stable Video
Diffusion, AnimateDiff, CogVideoX, Mochi-1) needs a CUDA GPU with several
GB of VRAM and tens of seconds to minutes of generation time per clip
*even on that GPU*. There is no CPU-only path that produces a usable
marketing clip within an HTTP request's lifetime, and this deployment
target (Render `free`, no GPU at any price tier this project has approved
using) cannot run one at all.

### External providers surveyed

| Provider | Text-to-video | Image-to-video | Free tier (no card) | Async support | Typical generation time | Duration/resolution | Notes |
|---|---|---|---|---|---|---|---|
| Runway (Gen-3/Gen-4) | Yes | Yes | No - paid plans, card required | Yes | Minutes | Up to ~10s clips, up to 1080p | Paid only |
| Pika | Yes | Yes | Limited trial credits, card required for real use | Yes | Minutes | Short clips, up to 1080p | Paid only |
| Luma Dream Machine | Yes | Yes | Limited trial credits, card required for real use | Yes | Minutes | ~5s clips, up to 1080p | Paid only |
| Stability AI (image-to-video) | No | Yes | No | Yes | ~1 min | ~4s clips, 1024x576 | Paid only |
| Google Veo | Yes | Yes | No (Gemini API billing) | Yes | Minutes | Varies | Paid only |
| Replicate-hosted open video models | Yes/varies | Yes/varies | No - pay-per-second GPU billing, card required | Yes | Varies (GPU-dependent) | Varies | Paid only |

Every one of these requires either a paid subscription or a credit-card-
backed pay-per-use billing account to produce a usable clip. A handful
advertise a small number of free trial credits at signup, but "trial
credits that still require a credit card on file" does not meet this
project's "no credit card, no paid activation" requirement, so none is
treated as viable.

### Conclusion

1. **Can video generation be implemented now with current infrastructure?**
   No - no GPU, no viable CPU-only model.
2. **Can it be implemented without paid services?**
   No - every external provider surveyed that produces usable output
   requires paid/credit-card-backed billing.
3. **Implemented?**
   No (per 1 and 2 above - nothing to implement without a policy change).
4. **Exactly what's needed to enable it later:**
   Either (a) a paid video-generation provider account with billing
   enabled (Runway, Pika, Luma, Stability AI, or a Replicate-hosted open
   video model), or (b) a GPU-backed deployment target with several GB of
   free VRAM, replacing the current GPU-less free-tier hosting, to run an
   open-weight model. Both are infrastructure/business decisions requiring
   an approved budget, not something closable in code alone.
5. **Does the current architecture support adding it later without a
   redesign?**
   Yes - `image_generation.py` already establishes the exact pattern to
   follow: one `MARKETING_IMAGE_PROVIDER`-style env var, one function per
   provider, a typed error/status vocabulary
   (`NOT_CONFIGURED`/`PROVIDER_ERROR`), and a capabilities field the
   frontend already reads and renders distinctly. A future
   `MARKETING_VIDEO_PROVIDER` + one router endpoint following the same
   shape is the whole integration surface; nothing about `campaigns`'
   schema, the router, or the frontend's capability-driven rendering needs
   to change to add it.

## Summary of environment variables

See `backend/.env.example`'s own "AUTOMATED MARKETING: AI IMAGE
GENERATION" section for the authoritative, always-up-to-date list with
inline explanations. In short: `MARKETING_IMAGE_PROVIDER` (unset by
default), plus provider-specific knobs (`HUGGINGFACE_API_TOKEN`/
`HUGGINGFACE_IMAGE_MODEL` for `huggingface`; `POLLINATIONS_BASE_URL`/
`MARKETING_IMAGE_WIDTH`/`MARKETING_IMAGE_HEIGHT` for `pollinations`, all
optional overrides). `MARKETING_BACKGROUND_REMOVAL_PROVIDER` (unset by
default - see section 1a above for why) plus `REMBG_MODEL` (optional
override, defaults to the smallest available, `u2netp`) for `rembg`. No
video-related environment variable exists, since no provider is
implemented.

## Privacy note: what leaves this service

Pollinations and Hugging Face (when configured) both receive the
generated text *prompt* only - never the tenant's uploaded product photo,
since neither provider is wired to accept one (see section 1a). rembg (when
configured) runs entirely locally in this service's own process - the
uploaded image is never sent to any third party for background removal.
No uploaded image or generated prompt is sent anywhere unless a provider
is explicitly configured via the env vars above.

## 1b. Free multi-account provider pool (2026-10-17)

Five free providers are tried per request, **one chain entry per account**
(`huggingface#1`, `huggingface#2`, `cloudflare#1`, `together#1`, then the
keyless `aihorde` and `pollinations`). Keyed accounts are shuffled so load and
free daily allowance spread evenly; an account that is out of allowance, rate
limited, or rejected is set aside (Redis, per account) for its Retry-After
while the others keep serving. Each extra free account is more free images per
day - list them comma-separated in `HUGGINGFACE_API_TOKENS`,
`CLOUDFLARE_ACCOUNTS` (`account_id:token`), `TOGETHER_API_KEYS`,
`HORDE_API_KEYS`, `POLLINATIONS_API_KEYS`. The older single-account variables
still work.

**Which provider made an image is never exposed.** The API returns
`image_generation_provider: "ai"`, `/marketing/options` reports
`provider: "ai"`, and the per-attempt list is not returned. The real name is
only in the server log.

**Verified live 2026-10-17 (this sandbox's network was open):**
- AI Horde, anonymous key: accepts jobs and returns real images, but the queue
  was ~75s once and over 240s another time. It is a last-resort fallback, not
  something to rely on. Sizes must be multiples of 64 or it answers HTTP 400.
- Pollinations keyless: HTTP 402 at first, later served images - but with a
  visible "pollinations.ai" watermark and garbled text, which exposes the
  provider and is not shippable. It is therefore **never used without a key**
  (free key: enter.pollinations.ai); 402/429 are treated as "busy" for 15 min.
- AI Horde also answered HTTP 403 after many rapid anonymous test jobs
  (throttling); the chain falls through to the next account/provider.
- Hugging Face, Cloudflare, Together: endpoints reachable (401 without a key);
  generation with a real key is covered by mocked tests only - no key was
  available to test live.

**What "works with nothing to configure" honestly means:** with no keys the
Studio still tries AI Horde and says plainly if it cannot produce an image. For
reliable, fast generation add at least one free Hugging Face token and one
Cloudflare account (about five minutes, no card) in Render's dashboard.
