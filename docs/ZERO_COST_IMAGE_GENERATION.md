# Zero-cost marketing images: how KEEL makes them, and how many

KEEL makes marketing images with an open-weight diffusion model running on a machine you already have. No image
API, no subscription, no credits, no rented GPU: the only cost is electricity for that machine. Campaign copy can
come from an open-weight language model on the same machine.

Everything below was run for real on 2026-10-22 in the development sandbox (results in section 6). Nothing in
this document is an estimate unless it says so.

## 1. The models (verified licences, legitimate free source)

| Use | Model | Licence | Commercial use | Where it comes from | Size |
|---|---|---|---|---|---|
| Images | **Stable Diffusion XL 1.0 base** (Stability AI) | CreativeML Open RAIL++-M | Allowed for the model and the images, within the licence's use restrictions (no unlawful, harmful, deceptive, discriminatory or privacy-violating uses; pass the restrictions on to anyone you give the model to) | Docker Hub's official model catalog `docker.io/ai/stable-diffusion:latest` (published by Docker), no account needed, checked against the registry's sha256 digest | 6.5 GB |
| Copy | **Qwen3-4B-Instruct-2507** (Qwen), 4-bit GGUF | Apache-2.0 (read from the file's own metadata: `general.license = apache-2.0`) | Allowed | `docker.io/ai/qwen3:4b-instruct-2507-q4_K_M`, digest-checked | 2.5 GB |

Why these: SDXL is the strongest image model with a commercial-use licence that could be obtained for free from
this environment and that runs on a CPU. (FLUX.1 [schnell] is Apache-2.0 too, but no free source for its weights
was reachable here, and it needs more memory.) Hugging Face could not be used: the token configured for this
environment is expired, which blocks even public downloads. Qwen3-4B writes good English and Arabic in a 2.5 GB file.

Known model limits: SDXL cannot write legible text, so labels on products come out as invented letters (the
negative prompt reduces but doesn't remove this; add real text in a design tool or use KEEL's copy alongside the
image); it doesn't reproduce a specific real product from a photo (text-to-image only).

## 2. What runs where

```
Studio ──> API ──> image_generation_jobs (Postgres, per-company RLS)
                        │  claim (fair: companies take turns; crashed workers' jobs taken over)
                        v
                 image worker(s)  python -m src.ai.marketing.image_worker
                        │  OpenAI images API (+ seed)
                        v
                 image server(s)  backend/image_server (SDXL via diffusers; one image at a time)
                        │
                        v
       object storage (gallery, per-company prefix) ──> Studio gallery: preview, download, attach, delete
```

- `backend/image_server/` - FastAPI service that loads the model once and serves `POST /v1/images/generations`
  and `GET /health` (device, busy, seconds per image, memory). GPU (float16) when present, else CPU (bfloat16 on
  CPUs with AMX / AVX512-BF16, else float32). Returns JPEG (quality 93) by default: about 200-300 KB per image
  instead of ~1.5 MB PNG, so plan storage holds ~5x more images.
- `src/ai/marketing/image_worker.py` - takes jobs from the queue: heartbeats while working, "all servers busy"
  re-queues without using an attempt, real failures retry with backoff (1, 4, 16 min; 3 attempts by default),
  a job whose worker died is taken over after 15 min, SIGTERM finishes the current image then stops.
- Several machines: list every server in `LOCAL_IMAGE_BASE_URLS`; the worker runs one thread per server.

## 3. Capacity (measured, not promised)

Measured on the development sandbox: 4 vCPU Intel Xeon (Sapphire Rapids class, AMX), 16 GB RAM, no GPU. SDXL base,
20 steps (DPM-Solver++ Karras), bfloat16.

| Measure | Value |
|---|---|
| Model load | 8-10 s |
| Memory: image server, steady | 8.2-8.4 GB resident (peak 12.5 GB while loading) |
| Memory: copy model server | about 3 GB |
| Seconds per image, machine otherwise idle | 141-153 s (1024x1024: 143-153 s; 1344x704: 141 s) |
| Seconds per image while another heavy job shares the CPU | 155-235 s |
| Images per hour, one 4-core server | **about 24** |
| Images per day, one 4-core server running all day | **about 580** |
| Campaign copy (Qwen3-4B, CPU) | about 60-70 s per campaign; short replies in seconds |
| Storage | 200-290 KB per image (JPEG) - about 0.25 GB per 1,000 images |

Scaling is linear in machines: each extra server adds its own images per hour (a second 4-core machine: ~48/h in
total). A machine with an NVIDIA GPU is much faster per image; that was **not measured here** (no GPU available),
so measure it with `scripts/real_image_check.py` before planning around it. KEEL's capacity view
(`GET /marketing/image-capacity`, shown in the Studio as an estimate) always uses the speed measured over the last
hour, never an assumed one.

Limits, all settings (backend/.env.example):
- `MARKETING_IMAGE_BATCH_MAX` (200): images per request - a guard against typos.
- `MARKETING_IMAGE_QUEUE_MAX_PER_COMPANY` (2000): unfinished images one company may have waiting (about 3.5 days
  of one CPU server) so one company can't block everyone; companies are also served in turn.
- Plan image count: images made only by self-hosted servers don't use it
  (`MARKETING_SELF_HOSTED_IMAGES_USE_PLAN_ALLOWANCE=false`); hosted providers still do. Plan **storage** always applies.

## 4. Set it up on a machine you own (no rental)

Requirements: Linux/macOS/Windows with Docker or Python 3.11; **about 16 GB RAM** (image server 8.5 GB + copy
model 3 GB + OS) on a modern 4+ core CPU, or an NVIDIA GPU with 8 GB+ VRAM; about 15 GB of disk for the models.
The 512 MB Render web service cannot run either model.

```bash
cd backend
scripts/fetch_image_model.sh ./models          # SDXL 1.0 base, 6.9 GB download, digest-checked, unpacked
scripts/fetch_llm_model.sh ./models            # optional: Qwen3-4B for free copy, 2.5 GB
python scripts/apply_migrations.py             # adds the image queue tables

# With Docker (image server + worker; the API's own settings below):
docker compose --profile local-images up -d
docker compose --profile local-llm up -d       # optional copy model on :8090

# Without Docker:
pip install -r image_server/requirements.txt
KEEL_IMAGE_MODEL_DIR=./models/sdxl-base-1.0 uvicorn image_server.server:app --host 0.0.0.0 --port 7860
python -m src.ai.marketing.image_worker        # next to the API, same environment as the API
```

API / worker settings (names only):
`MARKETING_IMAGE_PROVIDERS=local`, `LOCAL_IMAGE_BASE_URL=http://<image-server>:7860` (or `LOCAL_IMAGE_BASE_URLS`
for several), `LOCAL_IMAGE_TIMEOUT_SECONDS=900` on CPU, and for copy `LOCAL_LLM_BASE_URL=http://<llm>:8090/v1/chat/completions`,
`LLM_PROVIDERS=groq,local` (or `local` alone), `LOCAL_LLM_TIMEOUT_SECONDS=600` on CPU.

If the image machine is not on the same network as the API: put both behind a private network (e.g. a free
Tailscale or Cloudflare Tunnel account) rather than opening a port, and set the same secret as
`KEEL_IMAGE_API_KEY` on the image server and `LOCAL_IMAGE_API_KEY` on the API/worker.

Check it end to end (makes real images, verifies ratio, gallery, download and that the pixels are not a
placeholder):

```bash
python -m scripts.real_image_check --api http://localhost:8000 --email you@example.com --password '...' --variations 2
```

## 5. What is not free, and is never switched on

No paid provider is enabled by this setup: `MARKETING_IMAGE_PROVIDERS=local` uses only your servers. Hosted image
providers (Cloudflare, Hugging Face, Together, Gemini, Pollinations, AI Horde) are only used if you add their keys
and list them; their free allowances are limited and some become paid beyond them. Groq is only called if its key
is set and a price is recorded. Free cloud tiers that require a payment card were not used.

## 6. Results of the real runs (2026-10-22, development sandbox)

See `docs/AI_MODEL_MARKETING_IMPLEMENTATION.md` section 7 for the full test table.
