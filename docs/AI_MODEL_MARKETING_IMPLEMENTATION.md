# KEEL: AI model, image generation and Marketing integration

Branch `claude/peaceful-planck-083t1y`, 2026-10-21/22. **For zero-cost image generation (self-hosted SDXL, the
image queue, measured capacity and setup) see `docs/ZERO_COST_IMAGE_GENERATION.md`.** This builds on what was already in the repository
(the Groq/local/Hugging Face/paid language-model client, six hosted image providers with failover, the
designed-poster fallback and the Marketing Studio). It does not replace any of it.

Repository: `Huda-Hassouneh/CEOPRO-AI` (verified as the KEEL repository; `360-Radar` was not touched).
`docs/FINAL_SYSTEM_AUDIT.md` does not exist in this repository; the handoff documents used were
`CURRENT_STATUS.md`, `backend/PENDING_ACTIONS.md`, `backend/MARKETING_AI_CAPABILITIES.md` and
`docs/STAGING_BILLING_RUNBOOK.md`.

## 1. What changed

| Area | Before | Now |
|---|---|---|
| Language model | Exactly one provider (paid > Hugging Face > local > Groq). A bad key, a used-up quota or an unpriced model stopped the assistant and campaign writing. | Optional fallback chain `LLM_PROVIDERS` (for example `groq,local`): the next provider answers when one is not configured, rejects its key, is rate limited, is down, returns a malformed answer, or has no confirmed price. Each provider has its own circuit breaker. Unset, behaviour is exactly as before. |
| Image formats | Always 1024x1024 square. | Five formats: square 1:1, portrait 4:5, story/reel 9:16, landscape 16:9, link ad 1.91:1. Each provider is asked for the shape where its API allows it, and every result is centre-cropped to the format's ratio (kept unchanged if already within 2%). The designed fallback is drawn at the platform's size (1080x1080, 1080x1350, 1080x1920, 1920x1080, 1200x628). |
| Self-hosted images | Not supported. | `LOCAL_IMAGE_BASE_URL`: an image server on your own hardware, using the OpenAI images API (LocalAI, stable-diffusion.cpp server) or AUTOMATIC1111's txt2img API (AUTOMATIC1111, Forge, SD.Next). It is tried first when set. |
| Campaign images | One image per campaign; making a new one deleted the old one. | A gallery per campaign (`campaign_image_assets`, row-level security). Every image is kept with its format, prompt, channel and how it was made. One image is attached to the campaign; any other one can be attached, labelled with a channel, downloaded or deleted. |
| Image prompt | Built automatically, not editable. | Shown in the Studio and editable before each image; the edited text is sent and kept for next time. |
| Studio UI | Regenerate and download. | Format picker (also when creating the campaign), "where it will be used", prompt editor, preview in the right shape, gallery with "Use for campaign", channel, download and delete, plus loading, error, retry, empty, plan-limit and "AI images off" states. English and Arabic (right to left). When AI images are off, the Studio now still makes a designed image instead of none. |

## 2. Model choice and why

### Hardware this has to fit

| Where | Resources | Can it run a model? |
|---|---|---|
| Render free web service (`keel-ai-staging`, per `render.yaml`) | 512 MB RAM, a fraction of a CPU, no GPU | No. It already uses about 360 MB for the API and embeddings. Language and image models must be hosted elsewhere. |
| A developer laptop or Codespace (4 cores, 8-16 GB) | CPU only | A 1.5B-7B language model (quantized GGUF) through llama.cpp at roughly 5-15 tokens/s; image diffusion is possible but slow (tens of seconds to minutes per image). |
| A machine with an 8 GB+ GPU | GPU | Language and image models at usable speed. |
| This sandbox | 4 cores, 15 GB, no GPU | Could run small models, but no model weights could be downloaded: the network allows only PyPI, and every Hugging Face download is sent with an expired token (401). |

### Language model

| Option | Arabic and English | Business analysis and marketing copy | Structured output / tools | Cost | Fits | Role |
|---|---|---|---|---|---|---|
| Groq, `openai/gpt-oss-20b` (open weights, Apache-2.0) | Good | Good | JSON mode and tool calls | Groq's free tier is rate-limited, not unlimited; paid beyond it. KEEL refuses calls until a price is recorded (`billing_admin set-price`), by design. | No local footprint | **Primary (unchanged)** |
| llama.cpp `llama-server` + Qwen2.5 Instruct GGUF (already in `docker-compose.yml`, profile `local-llm`) | Good for its size (Qwen2.5 was trained on Arabic) | Adequate at 3B, good at 7B | JSON via the prompt; the client retries without JSON mode when refused | Free per call; you pay for the machine | 1.5B about 1.5 GB RAM, 3B about 2.5 GB, 7B about 5-6 GB | **Fallback** (`LLM_PROVIDERS=groq,local`) |
| Hugging Face Inference Providers (`HUGGINGFACE_LLM_MODEL`) | Depends on the model | Depends on the model | OpenAI-compatible | Monthly free credit is small; paid beyond it | No local footprint | Optional |
| Paid OpenAI-compatible vendor (`PAID_LLM_*`) | Depends | Depends | Yes | Paid | No local footprint | Only if listed; never an automatic fallback |

**Licence warning (verify before commercial use):** the repository's default local model is
**Qwen2.5-3B-Instruct**. To my knowledge it is released under the *Qwen Research License* (non-commercial),
unlike Qwen2.5-1.5B-Instruct and Qwen2.5-7B-Instruct, which are Apache-2.0. I could not open the model card from
this sandbox to re-check. If confirmed, switch the local model to **Qwen2.5-7B-Instruct** (8 GB+ machine) or
**Qwen2.5-1.5B-Instruct** (small machine) in `docker-compose.yml` and `scripts/download_local_llm_model.py`.

### Image model

| Option | Quality for ads | Cost | Notes |
|---|---|---|---|
| Cloudflare Workers AI, FLUX.1 [schnell] (Apache-2.0) | Good | Daily free allowance per account, then paid (never switched on here) | Ignores the requested size, so its square images are cropped to the format |
| Hugging Face Inference, FLUX.1 [schnell] / SDXL | Good | Small monthly free credit | Size honoured |
| Google AI Studio (`gemini-2.5-flash-image`) | Good | Free-tier key with limits | Nearest supported aspect ratio, then cropped |
| Together, FLUX.1-schnell-Free | Good | Free model with a key; rate-limited | Size honoured |
| AI Horde (community) | Fair | Free; anonymous jobs can queue for minutes | Sizes rounded to multiples of 64 |
| Pollinations | Good | Keyed use only (the keyless tier watermarks) | Size honoured |
| **Self-hosted** (new): SDXL / SD 1.5 / FLUX via AUTOMATIC1111, Forge, SD.Next, LocalAI or stable-diffusion.cpp | Depends on the model | Free per image; your hardware | Needs a GPU for comfortable speed. Check each model's licence (FLUX.1 [schnell] is Apache-2.0; SDXL uses CreativeML Open RAIL++-M; SD-Turbo / SDXL-Turbo use Stability's own licences) |
| Designed poster (built in) | Clean layout from the campaign's own text and photo, not AI | Free, local, always available | The last fallback; labelled "Designed" |

**Chosen:** keep the free hosted chain as the default on the 512 MB service, put a self-hosted server first
wherever the operator has the hardware, and keep the designed poster as the guaranteed last step. Nothing
here is unlimited: every hosted free tier has daily or monthly limits and rate limits.

## 3. What is free and what is not

| Service | Status |
|---|---|
| Designed poster, self-hosted image server, local llama-server | Free per use; the machine is your cost |
| Groq free tier | Free with rate limits; paid tiers exist. KEEL needs a confirmed price before any Groq call |
| Cloudflare Workers AI | Free daily allowance; paid plan needed beyond it (KEEL never enables it) |
| Hugging Face | Free monthly credit (small); paid beyond it |
| Google AI Studio, Together free model, AI Horde, Pollinations (keyed) | Free with limits; no service guarantee |
| Paid LLM vendor | Paid; used only when listed explicitly |

No limit was added to the application. The limits that apply are the providers' own, the plan allowances
already in KEEL (images per period, storage, AI Credits) and the storage space each kept image takes.

## 4. Configuration (names only; values go in `backend/.env` or the hosting dashboard)

Language model: `GROQ_API_KEY`, `GROQ_MODEL`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_TIMEOUT_SECONDS`,
`HUGGINGFACE_API_TOKEN`, `HUGGINGFACE_LLM_MODEL`, `PAID_LLM_BASE_URL`, `PAID_LLM_API_KEY`, `PAID_LLM_MODEL`,
**`LLM_PROVIDERS`** (new).

Images: `MARKETING_IMAGE_PROVIDERS`, `MARKETING_IMAGE_KEYLESS`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNTS`, `HUGGINGFACE_API_TOKEN(S)`, `TOGETHER_API_KEYS`, `GEMINI_API_KEYS`, `HORDE_API_KEYS`,
`POLLINATIONS_API_KEYS`, `MARKETING_IMAGE_TIMEOUT_SECONDS`, **`LOCAL_IMAGE_BASE_URL`, `LOCAL_IMAGE_API`
(`openai` or `a1111`), `LOCAL_IMAGE_MODEL`, `LOCAL_IMAGE_API_KEY`, `LOCAL_IMAGE_STEPS`,
`LOCAL_IMAGE_TIMEOUT_SECONDS`** (new).

Prices (database, not environment): `python -m scripts.billing_admin set-price ...`. The self-hosted image
server is priced at $0 by migration `20261029000000`.

## 5. Architecture

```
Studio (MarketingStudioPage, CampaignEditor, ImageStudio)
  -> POST /marketing/campaigns {..., generate_image, image_format}
  -> POST /marketing/campaigns/{id}/generate-image {image_format?, prompt?, channel?, attach?}
  -> GET  /marketing/campaigns/{id}/assets
  -> GET  /marketing/campaigns/{id}/assets/{asset_id}/image      (streamed through the API, never a storage URL)
  -> PATCH /marketing/campaigns/{id}/assets/{asset_id} {attach?, channel?, clear_channel?}
  -> DELETE /marketing/campaigns/{id}/assets/{asset_id}
routers/marketing.py
  copy:  content_generator -> rag/llm_client (provider_chain: LLM_PROVIDERS)
  image: image_generation.generate_campaign_image(prompt, image_format)
           local -> keyed free accounts (rotated) -> AI Horde      (each: request size -> verify -> crop)
         on failure: designed_poster.render_designed_poster(campaign, photo, size)
  store: MinIO / S3-compatible bucket ceopro-marketing-generated-images, key {tenant}/{campaign}/...
         campaign_image_assets row (+ tenant_storage_objects for plan storage)
         campaigns.generated_image_key = the attached image
```

Security properties:

- Every query runs on the company's row-level-security connection; the new table has `FORCE ROW LEVEL
  SECURITY` and a policy on `get_current_tenant()`; an asset is always looked up together with its campaign id.
- The image stream also checks that the stored key sits under the company's own prefix.
- Which provider or model made an image is stored for operators only and never returned by the API.
- No secrets are stored with assets; the prompt is campaign text written to be published.
- Plan image allowance and storage are reserved before a provider is called and returned when nothing is made.
- Deleting an image deletes its file and frees its storage; deleting a campaign deletes every file under it.

## 6. Setup and deployment

1. Apply migrations: `cd backend && python scripts/apply_migrations.py` (adds `campaign_image_assets`, backfills
   each existing campaign's image as its first, attached asset, and adds the $0 local image price). Rollback:
   `src/infrastructure/database/rollback/20261029000000_add_campaign_image_assets.down.sql`.
2. Language-model fallback (optional): run `docker compose --profile local-llm up llm-local` on a machine with
   enough RAM (see the licence warning above), set `LOCAL_LLM_BASE_URL=http://<host>:<port>/v1/chat/completions`
   and `LLM_PROVIDERS=groq,local`. Check with `./keel llm-check` (prints the chain).
3. Self-hosted images (optional): run an AUTOMATIC1111/Forge server with `--api` (or LocalAI) on a GPU machine
   reachable from the API, set `LOCAL_IMAGE_BASE_URL` and `LOCAL_IMAGE_API`. Never on the 512 MB service.
4. Nothing else changes for the hosted image chain; existing keys keep working.
5. Deploy order: backend (migration first), then frontend. Staging before production.

## 7. Tests run and results

All on the development sandbox against real local services: Postgres 15 + pgvector (Docker), Redis 7 (Docker),
MinIO built from source. The remote Render database present in this session's environment was never used. No
staging or production system was touched.

### 7.1 Real models (2026-10-22) - no stand-ins

| Check | Result |
|---|---|
| SDXL 1.0 base downloaded from `docker.io/ai/stable-diffusion` and verified against the registry digest | PASS |
| Direct benchmark, one real image per format (20 steps, CPU bfloat16) | PASS: square 172 s, portrait 145 s, story 162 s, landscape 154 s, wide 235 s (CPU shared with a compile) |
| `real_image_check`, batch 1: 5 formats through API -> queue -> worker -> SDXL -> storage -> gallery -> download | **5/5 PASS**, 141-153 s each (CPU idle) |
| Copy written by the local model: Groq rejected (401), Qwen3-4B (Apache-2.0) answered via `LLM_PROVIDERS=groq,local` | PASS (67 s; English copy, hashtags, CTA, image prompt) |
| `real_image_check`, batch 2: that campaign, 3 formats x 2 variations | First attempt **0/6 FAIL**: the image server was OOM-killed (copy model loaded at the same time). Jobs retried and were then marked FAILED, as designed. After the fixes (see 8): **6/6 PASS**, 120-145 s each, variations distinct (mean pixel difference ~66) |
| Browser E2E `marketing-batch.mjs`, English 1440px: create campaign (real copy), first image via queue in 4:5, "Make many images" square + landscape, progress, download, attach, cross-company 404 | **PASS** (12 min; 3 real images, 181-218 s each with the browser sharing the CPU) |
| Browser E2E, Arabic 390px (right to left), same steps | **PASS** (11 min; Arabic copy from the local model; 3 real images, 154-226 s each) |
| Realism check: every image above has 20k-60k distinct colours and edge detail 24-30; a flat or gradient placeholder fails the same check | PASS |

### 7.2 Automated suites

| Check | Result |
|---|---|
| Backend suite before any change (baseline) | 3502 passed, 23 skipped, 0 failed |
| Backend suite on the final tree (after merging `main`) | 3588 passed, 23 skipped (need external services, same as baseline), 0 failed |
| New: image queue integration tests (batch of formats x variations, retry with backoff then FAILED, busy re-queue without using an attempt, takeover of a dead worker's job, companies take turns, limits, cancel/retry, capacity, isolation via API and RLS, plan allowance rule) | 8 passed (skip when another company's jobs are queued) |
| New: image server unit tests (sizes, one at a time, low-memory guard, key, seeds, JPEG response) | 9 passed |
| New: LLM fallback chain tests | 19 passed |
| Image provider / format tests | 47 passed |
| Gallery integration tests | 13 passed |
| Frontend lint / unit tests / production build | clean / 113 passed / passes |
| Browser smoke test of every screen, English desktop / Arabic mobile / dark, with the queue UI and a live worker | 27/27 clean in each |
| Accessibility audit (axe, WCAG 2.1 AA) of every screen plus an open campaign with 3 real images and the batch panel, three modes | 0 findings in each |
| Application Knowledge Registry validator | OK (12 entries) |

In total: 17 real SDXL images went through the full product path (5 + 6 + 3 + 3), plus 7 direct image-server
benchmark images. Bug found by the Arabic run and fixed: a download named after an Arabic campaign title was
saved as plain "download" by Chrome; download names are now ASCII.

## 8. Known limitations and blockers

- **Hardware, measured:** SDXL on CPU needs 7.8 GB idle and **10.2 GB at peak** per image. On a 16 GB machine it
  cannot share memory with the copy model (3.4 GB) and the app: the server was OOM-killed twice here before the
  guard was raised. The image server now answers "busy" below 3 GB free, so jobs wait instead of crashing. Run
  the copy model on another machine, use 24 GB+, or stop it while images are made (what the sandbox run did).
- **Speed:** about 24-27 images per hour per 4-core CPU server (measured); more needs more machines you own, or a
  GPU (not measured here).
- **SDXL cannot write legible text:** product labels come out as invented letters. Prompts longer than 77 CLIP
  tokens are cut (SDXL's limit), so the end of a long image description is ignored.
- **Not tested on staging:** the sandbox cannot reach Render. The Render 512 MB service cannot host the models.
- Product-photo-preserving generation and video: not available (unchanged).
- The Hugging Face token configured for this environment is expired; the Groq key returns 401.
- Credentials exposed in public Git history: **open**, see `docs/SECURITY_CREDENTIAL_ROTATION.md`.
- Kept images use plan storage until deleted (about 0.25 GB per 1,000 JPEG images).
