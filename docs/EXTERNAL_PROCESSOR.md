# Overture for competitor discovery: the compact mirror (current) and the external processor

## Current design: the compact mirror (no processor, $0)

Measured 9 Nov 2026 on real Overture data (release 2026-10-21.0), local:

| Search | Reading Overture directly | Mirror (cell packs) |
|---|---|---|
| Amman 5 km | 13.7 s, 564 MB peak | 0.7–0.8 s, +16 MB cold / +4 MB warm |
| Dubai 15 km | 15.2 s, 963–1,002 MB peak | 2.2 s, +25 MB cold / +7 MB warm |

Candidate lists are identical; pyarrow is never loaded in the API process.

- **Build** (`backend/scripts/overture_mirror/build.py`, run by `.github/workflows/overture-mirror.yml`
  monthly and on demand): per 10° cell, keeps only open, confident places and only the fields discovery
  reads; writes `cell_<lon>_<lat>.pack` (one gzip member per 0.1° tile, one JSON place per line) and
  `cell_<lon>_<lat>.idx.json` (each tile's byte range), plus `cells.json` (release, licence, which cells are
  covered). `scripts/overture_mirror/verify.py` checks every tile before anything is published.
- **Publish**: assets of a pre-release `overture-mirror-<release>` in this public repository (free; data ©
  Overture Maps Foundation, CDLA-Permissive-2.0). Only public data is read or published.
- **Read** (`providers/overture.py::search_mirror`, mode `mirror`, the default whenever `OVERTURE_MIRROR_URL`
  is set): the API range-reads only the tiles covering a search and streams them line by line with the
  standard library. Guards: at most `OVERTURE_MIRROR_MAX_TILES` tiles per search, each at most
  `OVERTURE_MIRROR_MAX_TILE_BYTES`; a damaged place is skipped, a failing tile is counted, an unreachable
  mirror reports `unreachable` and the other sources still run. A region outside `covered` reports
  `not_covered`, never a false "no competitors".
- **Coverage**: `backend/config/overture_mirror_cells.json` (initially 20°W–60°E, 10°N–40°N: the Gulf,
  Levant, Egypt and North Africa). Add a cell there to extend it.

The external processor below remains supported (`OFFLOAD_PROCESSOR_URL`) but is not needed.

# External processor for heavy work

Status: **prototype, tested locally only. Not deployed and not connected to production.**
Nothing in Render, production environment variables, databases or Redis was changed.

## Why

On 6–7 Nov 2026 the production API (`ceopro-ai-new`, `api.keelai.net`, Render free plan,
512 MiB) was killed for memory twice, each time ~10–60 s after a competitor discovery run
started in the API process. While it restarted (~90 s on Render) every chatbot request failed
and the chat showed "Couldn't reach KEEL".

Measured locally with the real Overture dataset, the Overture step of discovery alone peaks at
**955–1,664 MB** (Amman 5 km / Dubai 15 km). On top of the API's ~364 MB idle size it can never
fit in 512 MiB. Reproduced in a 512 MiB cgroup: the API stand-in was SIGKILLed (exit 137)
9 s after a discovery started and in-flight chat requests failed.

## Architecture

```
browser ──► API (Render, 512 MiB, light)                     processor (external, free host)
            │  chat, app requests: unchanged                 │  FastAPI, holds no credentials
            │  discovery thread ── signed HTTPS ───────────► │  POST /v1/jobs  {kind, params}
            │     waits (sleeping thread, ~0 MB)             │   ├ same task already queued/running → joined
            │  ◄────────── result (JSON candidates) ──────── │   ├ same task done < 6 h ago → cached answer
            │  if the processor is down: Overture source     │   └ else: one fresh child process per task
            │  reports "processor_unavailable", the other    │       (crash/OOM fails that task only)
            │  sources still run, discovery completes        │  GET /v1/jobs/{id} · GET /healthz
            └─ GET /health/processor (monitoring)            └─ Overture index precomputed at start
```

- **API side** (`src/offload/client.py`, `providers/overture.py`): `OVERTURE_EXECUTION=auto`
  sends Overture to the processor when `OFFLOAD_PROCESSOR_URL` is set; with no processor the
  source is skipped (`needs_processor`) and the other sources still run. **The API never reads
  Overture in-process**, whatever memory the host reports: a limit isn't always readable, and even
  a large host shouldn't let one background job starve customer requests. Only an explicit
  `OVERTURE_EXECUTION=local` reads it in-process - the processor image sets it, and a development
  machine may; never the production API. After a deploy, `GET /health/processor` shows
  `"overture": "unsafe"` (no processor) or `"remote"`.
- **Admission control** (`market_discovery/pipeline.py::run_with_slot`): every discovery run in
  the API process - "Refresh scan" and the scheduled weekly refresh - takes one of
  `DISCOVERY_MAX_CONCURRENT` slots (default 1). Others wait as "queued"; a run that gets no slot
  within `DISCOVERY_SLOT_WAIT_SECONDS` (default 600, always under the 15-minute stale-run limit)
  is closed as failed (`busy`) without being charged. Retries with backoff and
  `Retry-After`, a hard deadline (200 s, inside discovery's 240 s), and a circuit breaker
  (3 failures → no calls for 60 s; callers get the fallback in < 1 ms).
- **Processor** (`src/offload/processor.py`, `Dockerfile.processor`): HMAC-SHA256 signed
  requests with a timestamp (5 min replay window); bounded parallelism and queue, `429 +
  Retry-After` when full; job id = hash of the task, so a retry, double click or two companies
  asking the same thing run it once; results cached 6 h; child processes get
  `oom_score_adj=1000` so the kernel kills a task, never the server.
- **Data sent out**: place (rounded to ~1 m), radius, trade words and map categories only. No
  tenant id, company name, website, customer records or credentials leave the API.
- **Efficiency work in the shared code** (benefits every host): the Overture index is a compact
  per-row-group bounding-box list (JSON, < 1 MB) instead of every file's full Parquet footer
  (~330 MB held in memory, pickled), and rows outside the search box are dropped in Arrow
  before Python objects are made. Output verified **identical** to the previous code in 6 real
  cases (3 cities × cold/warm).

## Free options compared (limits checked Nov 2026)

| Option | Free limits | Fits? | Why |
|---|---|---|---|
| **Hugging Face Spaces, Docker, CPU basic** | 2 vCPU, 16 GB RAM, 50 GB ephemeral disk, $0, no card; sleeps after 48 h without traffic | **Chosen** | Always-free, enough memory for ~15 parallel Overture tasks, runs our container unchanged, nothing billed unless hardware is upgraded by hand |
| Oracle Cloud Always Free (Ampere A1) | 4 OCPU / 24 GB by Oracle's docs; reports of a cut to 2 / 12 GB from June 2026; idle VMs reclaimed (CPU p95 < 20% over 7 days); card for identity; capacity often unavailable | Runner-up | Most capacity, but a VM to patch and secure, and the reclamation/capacity risks |
| GitHub Actions (repo is public) | Standard runners free and unlimited on public repos (4 CPU / 16 GB) | No | GitHub's terms forbid using Actions as part of a serverless application; run logs and artifacts of a public repo are public; 20–60 s start per job |
| Cloudflare Workers free | 10 ms CPU, 128 MB, 100k requests/day | No | Cannot run pyarrow / Overture |
| AWS free plan (accounts after 15 Jul 2025) | Up to $200 credits; plan ends after 6 months or when credits run out | No | Not permanently free; card required |
| Google Cloud Run | Needs a billing account; usage beyond free tier is billed | No | Usage-based billing |
| Modal | $30/month credits | No | Usage-based; billing beyond credits |

## Benchmarks (local, this repository's code, real Overture data)

Machine: 4 vCPU / 16 GB sandbox. The API stand-in (`scripts/benchmarks/offload/api_sim.py`)
ran in a **real 512 MiB memory cgroup** holding 290 MB of ballast to match production's
measured ~364 MB idle size, pinned to 2 CPUs; the processor ran outside it on 2 other CPUs
(the size of a free Space). Chat requests cost a little CPU plus a 300 ms simulated
language-model wait. The stand-in is not the real KEEL API (no database or Groq), so the
absolute chat numbers describe the stand-in; what they show is the effect of discovery on it.

**A. Today's design (Overture inside the API), 10 chat users:** API killed for memory
(exit 137) 9 s after discovery started; 60 chat requests failed (10 in flight, 50 refused
while restarting); the discovery result was lost. Restart locally ~1 s, on Render ~90 s.

**B. Offloaded, same load:** 2,968 / 2,968 chat requests OK, no restart. Chat p95: 311 ms
before discovery, 307 ms during. API memory max 373 MB (+9 MB). Discovery done (682 places,
13.4 s, cold cache). Processor tree peaked at 658 MB and returned to 82 MB.

**C. Load ramp with 5 discoveries per step (offloaded):**

| chat users | errors | throughput (req/s) | p50 / p95 ms, no discovery | p50 / p95 ms, 5 discoveries | API memory max |
|---|---|---|---|---|---|
| 1 | 0 | 3.3 | 303 / 304 | 303 / 304 | 377 MB |
| 10 | 0 | 33 | 304 / 310 | 303 / 308 | 383 MB |
| 25 | 0 | 82 | 303 / 312 | 303 / 311 | 390 MB |
| 50 | 0 | 133 | 349 / 508 | 339 / 519 | 399 MB |
| 100 | 0 | 135 | 684 / 902 | 687 / 875 | 406 MB |

25,775 chat requests, 0 errors, 0 restarts, all 25 discoveries finished. Discovery made no
measurable difference at any step. The flattening at ~135 req/s is the stand-in's 40-thread
pool waiting on the simulated model call, not discovery.

**D. Processor container** (`Dockerfile.processor`, `--cpus=2 --memory=16g`):
healthy 0.6 s after start; Overture index precomputed 5.4 s after start; idle 216 MiB.

| test | result |
|---|---|
| 20 identical requests at once | 1 execution, 19 joined, all answered, 10.5 s |
| cached repeat (50×) | p50 17 ms, p95 23 ms |
| 12 distinct real searches at once | 25 s total, **28.9 jobs/min**, 0 failed, 8–25 s each |
| peak under that load | 883 MiB memory, CPU at the 2-vCPU limit (CPU is the bottleneck, not memory) |
| end to end: 25 chat users + 5 discoveries via the container | 4,925 / 4,925 chat OK, p95 310 ms, API max 378 MB, discoveries 14–23 s |

**E. Failures:**

| scenario | result |
|---|---|
| processor down | first call gives up in 6.5 s with `processor_unavailable`; then the breaker answers in 0.07 ms |
| processor killed mid-task, back after 3 s | client resubmitted, result delivered (593 places, 17.3 s) |
| 20 jobs into 2 running + 2 queued slots | 29 × 429 retried, 20 / 20 completed, each ran once |
| processor in a 1.2 GB cgroup, two ~970 MB tasks at once | kernel killed one task child (`oom_kill 1`); server PID unchanged; other task OK; next task OK in 8.2 s |

Reproduce: `scripts/benchmarks/offload/` (`compare.py` needs the previous provider saved as
`overture_old.py`: `git show 375055c:backend/src/market_scraper/market_discovery/providers/overture.py`).

## Limits and risks

- **Not load-tested on Hugging Face itself.** All numbers are from this sandbox with the
  processor limited to 2 CPUs. Network to Overture's bucket (AWS us-west-2) from a Space will differ.
- **Sleep:** a free Space sleeps after 48 h without requests; the first request wakes it (container
  start measured at 0.6 s locally plus platform scheduling, unmeasured). An uptime monitor
  calling `GET /health/processor` on the API every few hours keeps it awake and also alerts on failure.
- **No SLA.** Hugging Face may restart or pause free Spaces. KEEL degrades gracefully: only the
  Overture source is missing from that run; chat and the rest of discovery are unaffected.
- **Capacity:** ~29 distinct Overture searches per minute on 2 vCPU; identical/cached ones are
  ~20 ms. Above that the processor queues (32) and then answers 429 - it does not fall over.
- **Terms:** a Space used as a private backend is within normal Space use as far as we know, but
  Hugging Face's acceptable-use terms should be read before relying on it commercially.
- **Other discovery steps** (website reading, matching) still run in the API process; they were
  not measured separately. Overture alone explains both production crashes.

## Turning it on (needs approval - not done)

1. Create a **private** Docker Space on the KEEL Hugging Face account (CPU basic, free) from
   `backend/` with `Dockerfile.processor`, and the Space README front matter:
   `sdk: docker`, `app_port: 7860`.
2. In the Space's *Secrets*: `OFFLOAD_SHARED_SECRET` = 64 random hex characters.
3. On `ceopro-ai-new` (Render env vars - a production change): `OFFLOAD_PROCESSOR_URL`
   (the Space URL), the same `OFFLOAD_SHARED_SECRET`, and `OFFLOAD_PROCESSOR_TOKEN` (a
   read-only Hugging Face token, needed because the Space is private).
4. Deploy the API. Without steps 1–3 the API code still stops the crashes (Overture skipped).

Sources: [HF Spaces hardware](https://huggingface.co/docs/hub/en/spaces-gpus) ·
[HF manage Spaces (sleep)](https://huggingface.co/docs/huggingface_hub/main/guides/manage-spaces) ·
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) ·
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) ·
[Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits) ·
[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) ·
[AWS free plan](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/) ·
[Google Cloud free features](https://docs.cloud.google.com/free) · [Modal pricing](https://modal.com/pricing)
