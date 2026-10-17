# Apify in competitor discovery

How the Apify Google Maps source is wired into competitor discovery, what
was broken, what changed, and how to confirm it works on a real deployment.

## Status (17 Oct 2026)

| | State |
|---|---|
| Code and config on `KEEL_Test` | Done (commit `85b1152`): token name, header auth, no token in logs, `render.yaml` / compose / `.env.example` slots |
| Real Apify call through KEEL's pipeline | Verified once, outside staging: `execute_run` with Apify as the only source, one search phrase, `APIFY_MAX_PLACES_PER_SEARCH=1`, into a throwaway database. The actor answered 201, one Amman bakery was parsed and stored in `global_competitors` / `competitor_sources` (`source = apify_google_maps`, a Google place ID as `source_ref`, coordinates, rating 4.4, 30 reviews), and `discovery_runs.providers.apify_google_maps` read `{"status": "ok", "found": 1, "requests": 1}`. The full debug log of that run held no token, no `token=` and no `Bearer` value. |
| `APIFY_API_TOKEN` on `keel-ai-staging` | Not done: needs the Render dashboard (it is a `sync: false` secret), not reachable from the environment this was built in |
| Live run on staging | Not done: waits on the token above and a redeploy |

## What it is

`backend/src/market_scraper/market_discovery/providers/apify_maps.py` runs
Apify's Google Maps actor (`compass~crawler-google-places`) as one of the
competitor discovery sources, next to OpenStreetMap, Overture, Google Places
and web search. Each run is billed to the Apify account that owns the token.

Discovery runs inside the **`ai` service**: the "Refresh scan" background
task (`src/ai/routers/discovery.py`) and the scheduled refresh started in
`src/ai/main.py`. The workers' `discovery_worker` is a different code path
and does not use Apify, so the token belongs on the `ai` service only.

## What was wrong

Verified on `KEEL_Test` at commit `8b8c730`:

- The provider read `APIFY_TOKEN`, while `CURRENT_STATUS.md` and
  `scripts/live_credential_smoke_tests.py` use `APIFY_API_TOKEN`.
- No deployment file passed either name to the `ai` service: no slot in
  `render.yaml`, no entry in the `ai` service of `backend/docker-compose.yml`
  (which has no `env_file:`, so a value in `backend/.env` never reached the
  container), and nothing in `backend/.env.example`.
- So the provider reported `skipped / not_configured` and was never called.
  The run still finished as `completed` on the other sources, and the UI
  shows map sources as one combined "configured" entry, so the gap was not
  visible.
- The token was sent as `?token=` in the URL. On any failure the provider
  logged the httpx error text, which contains the full URL, token included.

The Apify API itself was checked live and returned real, correctly shaped
data, and `parse()` mapped every field it reads correctly.

## What changed

- `apify_maps.py` reads `APIFY_API_TOKEN`, with `APIFY_TOKEN` still accepted
  as the older name.
- The token goes in the `Authorization: Bearer` header, never the URL, so it
  can't reach logs, error text or the discovery cache key.
- Failures log only the HTTP status or exception type, and name the cause in
  the run's per-provider status: `auth_failed` (401/403), `timeout`, or
  `unreachable`. The run-level error shown to tenants is unchanged.
- `APIFY_API_TOKEN` is now declared for `keel-ai-staging` in `render.yaml`,
  passed to the `ai` service in `backend/docker-compose.yml` (with
  `APIFY_MAX_PLACES_PER_SEARCH`), and listed in `backend/.env.example` and
  `RUNNING_LOCALLY.md`.
- Tests in `backend/src/ai/tests/test_market_discovery.py`: both token
  names, token only in the header, failure reasons without the token in the
  logs, and a guard that the deployment files hand the token to the `ai`
  service.

## Turning it on

The value is never committed.

- **Render:** Dashboard → `keel-ai-staging` → Environment → set
  `APIFY_API_TOKEN` → save and redeploy.
- **Local Docker:** set `APIFY_API_TOKEN=` in `backend/.env`, then
  `docker compose up -d --force-recreate ai`. A plain restart does not pick
  up new environment values.

Then check inside the `ai` container (Render Shell, or
`docker compose exec ai ...`). This prints true/false, never the value:

```sh
python -c "import os; from src.market_scraper.market_discovery import pipeline; print('token present:', bool(os.getenv('APIFY_API_TOKEN'))); print(pipeline.provider_status())"
```

Expect `token present: True` and `apify_google_maps` with `'configured': True`.

## Confirming a real call (costs Apify credit)

The unit tests prove the code shape only. To prove KEEL calls Apify and
stores what it returns, with the account owner's approval:

1. Set `APIFY_MAX_PLACES_PER_SEARCH=1` on the `ai` service to keep the run
   to a few cents, and use a company with a city or coordinates.
2. Start a "Refresh scan" from the Competitors screen.
3. In the Apify console, confirm a new `compass~crawler-google-places` run
   at that time.
4. Check what KEEL recorded:

   ```sql
   SELECT created_at, status, providers->'apify_google_maps' AS apify
   FROM discovery_runs ORDER BY created_at DESC LIMIT 5;
   -- expect {"status": "ok", "found": >= 1, "requests": 1}

   SELECT gc.competitor_name, gc.phone, gc.latitude, gc.longitude, gc.rating, gc.review_count, cs.source_ref
   FROM competitor_sources cs JOIN global_competitors gc USING (global_competitor_id)
   WHERE cs.source = 'apify_google_maps' LIMIT 5;
   ```

5. Compare one stored row with the same place in the Apify run's dataset:
   name, place ID (`source_ref`), phone, coordinates, rating, review count.

Responses are cached in Redis for 24 hours (`market_discovery/http.py`). The
same keywords and location on the same day return the cached copy and start
no Apify run, so change the location or wait out the cache before reading
"no run in the console" as a failure. A `discovery_runs` status of
`auth_failed` means the token is wrong or lacks permission to run actors.

## Security follow-up

- Before this change, a failed Apify call logged the token. If any
  environment ever had `APIFY_TOKEN` set, search its API logs for
  "Apify run failed" and rotate the token if it appears.
- The social-media Apify spiders (`spiders/social_data_provider.py`,
  `spiders/video_transcript_provider.py`) read tokens from the credential
  vault and were not reviewed here. Check whether they put the token in a
  URL.

## Not done here

- `parse()` drops the Arabic business name. Apify's `subTitle` could fill
  `name_ar` when it is Arabic script.
- The 180-second client timeout covers up to 3 search phrases × 40 places.
  Larger searches may need Apify's asynchronous run API.
- A per-vendor provider status for operators would make a skipped paid
  source visible without querying the database.
