# Object storage on a free tier (Backblaze B2)

Status 2026-11-09, Session 4. Production (`ceopro-ai-new`, Render free plan, ephemeral disk) has no
`MINIO_ENDPOINT`, so Knowledge Base documents, data-import PDFs and stored marketing images are unavailable.
This records the choice of a free, no-card storage service, the code changes that make it safe to use, how it was
verified, and the owner and deploy steps.

## 1. Decision: Backblaze B2, one private bucket, provider caps at $0

| | Backblaze B2 (chosen) | Supabase Storage | Postgres `bytea` (no new account) | Cloudflare R2 / Render disk |
|---|---|---|---|---|
| Payment method | Not needed to create an account or to use the free 10 GB | Not stated on the pages found (unverified) | none | **Excluded**: R2 needs a card; a Render disk is paid |
| Free storage | 10 GB | 1 GB, 50 MB per file | Shares the production database's own storage limit | - |
| Availability | Always on | **Free projects are paused after a week of low activity** | As the database | - |
| S3 API | Yes, works with the existing `minio` client unchanged | Yes, but the endpoint has a path (`/storage/v1/s3`) the `minio` client can't use | No: every call site would be rewritten | - |
| Cost risk | Usage beyond free is billable **unless caps are set**: "not setting caps will result in an unlimited amount of use, and an unlimited amount of charges". Mitigated: every cap set to $0 (§3) **plus** KEEL's own 9 GB ceiling | Free plan: over-quota gives a notice and a grace period, no charges | None, but filling it takes down the whole product (sign-in, billing, every feature), not only uploads | - |
| Security | Private bucket, application key restricted to that one bucket, TLS only | Private bucket, S3 keys are project-wide | RLS already in place | - |

**Why not the database:** customer files would compete for the same free database quota as every tenant's
accounts, sales and billing records. One large upload could stop the whole service, and backups grow with file
data. That trades a storage outage for a full outage. Rejected.

**Why not Supabase:** a paused project would silently break uploads and stored images in production, 1 GB is
small, and its S3 endpoint has a path the existing client doesn't support. A second-best choice.

**Sources** (searched from the provider's own sites; the session's network blocked a direct page fetch, so the
owner should glance at the pricing page when signing up):

- [B2 Cloud Storage pricing](https://www.backblaze.com/cloud-storage/pricing): 10 GB free; no billing method
  needed to start; free egress up to 3x the average stored data.
- [Free isn't always free (Backblaze blog)](https://www.backblaze.com/blog/free-isnt-always-free-a-guide-to-free-cloud-tiers/):
  "you don't need to give us a credit card to create an account".
- [Data caps and alerts](https://www.backblaze.com/docs/cloud-storage-data-caps-and-alerts) and
  [How to use B2 data caps & alerts](https://help.backblaze.com/hc/en-us/articles/217931138-How-to-use-B2-data-caps-alerts):
  daily caps for storage, downloads, Class B and Class C transactions; alerts at 75% and 100%; uncapped means
  unlimited charges.
- [Native API errors](https://www.backblaze.com/docs/cloud-storage-native-api-error-handling-and-status-codes),
  [Integration checklist](https://www.backblaze.com/docs/cloud-storage-integration-checklist): a cap returns
  403 `cap_exceeded`; clients must stop and tell the user.
- [Understanding B2 pricing](https://help.backblaze.com/hc/en-us/articles/217667478-Understanding-B2-Pricing-Structure):
  2,500 free Class B (downloads) and 2,500 free Class C (listings) transactions per day.
- [Supabase pricing](https://supabase.com/pricing), [free project pausing](https://supabase.com/kb/faqs/platform/free-project-pausing).

**Not verified** (no provider page found): whether a B2 account *without* a payment method is blocked at 10 GB
automatically. The design does not rely on it: §3's $0 caps and KEEL's own limit both apply.

### Free-tier limits that matter day to day

- **Downloads (Class B): 2,500 per day.** Each image view or document read is one. KEEL now answers a repeat view
  of the same image with `304 Not Modified` from an ETag, without reading storage. Past the cap, image views fail
  until the next day (UTC) with "Could not read the stored image"; nothing is lost.
- **Listings (Class C): 2,500 per day.** KEEL lists the bucket to measure total usage at most once per
  10 minutes per process (about 150 per day per process), and `/health/storage` caches its answer for 5 minutes.
- **Storage: 10 GB.** KEEL refuses new files at 9 GB (`STORAGE_QUOTA_BYTES`), with HTTP 507 "File storage is
  full". Each plan's own storage allowance per company still applies first.

## 2. What changed in the code

- `backend/src/ai/core/object_storage.py` (new): `db.minio_client()` returns an `ObjectStore` with the same Minio
  methods call sites already use.
  - **Single-bucket mode** (`MINIO_BUCKET`): logical buckets become the first part of the key in one private
    bucket (`<bucket>/ceopro-rag-knowledge/uploads/<tenant_id>/<sha256>.pdf`). It never creates a bucket; a
    missing one is a clear configuration error. Without `MINIO_BUCKET` (local MinIO, CI) behaviour is unchanged.
  - **Limits**: `STORAGE_MAX_OBJECT_BYTES` (25 MiB per object) and `STORAGE_QUOTA_BYTES` (9 GB in single-bucket
    mode), checked before the write.
  - **Clear errors**: `StorageQuotaExceeded` → 507, `StorageUnavailable` → 503 (global handler plus the Knowledge
    Base upload route, which used to answer 500 for everything). A provider "cap exceeded" refusal counts as
    full. `NoSuchKey` and other S3 errors are raised unchanged.
  - **TLS**: where KEEL is deployed, a non-local endpoint must be `https://`. B2's region is read from its host.
- **Cross-tenant fix (found here):** assistant summaries were written by every company to the same object
  (`_generated/<slot>.txt`). A concurrent write by company B could be read and embedded into company A's index,
  and deleting one company's data deleted every company's summaries. The object is now
  `_generated/<tenant_id>/<slot>.txt` (`rag/data_access.storage_object_key`); the row path keeps its slot so the
  assistant's access rules are unchanged. Data-import PDFs now use `uploads/<tenant_id>/<job_id>.pdf`.
  Production never had storage, so no production object carries the old shared key. Old local MinIO objects
  are simply rewritten on the next summary refresh.
- `GET /health/storage`: `not_configured` / `ok` / `full` / `unavailable`, plus mode and % used. It is separate from
  `/health/ready`, so a storage outage never makes Render restart the API. It never shows the endpoint, bucket
  or keys.
- `config_check`: errors for http on a deployed remote endpoint, an endpoint with a path, an invalid bucket name or
  non-numeric limits. Warnings for a hosted endpoint without `MINIO_BUCKET` and for a quota above B2's free 10 GB.

- Storage calls time out in seconds (`STORAGE_CONNECT_TIMEOUT_SECONDS` 5, `STORAGE_READ_TIMEOUT_SECONDS` 60, 2
  retries). minio's own default was a 300 s timeout with 5 retries, so an outage held requests for minutes.
- Marketing screens show a localized (EN/AR) "storage is full" message for 507.

## 2a. Local verification (2026-11-09, Session 4)

Local services only: PostgreSQL 16 + pgvector (CI uses 17), Redis 7, and MinIO built from the exact pinned source in
`Dockerfile.minio` (`go install github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c`; Docker is not available
in this sandbox). No hosted URL or key was used; ambient hosted values were unset first.

End-to-end against a real API process (uvicorn), single-bucket mode, a private bucket, two synthetic companies:

| Check | Result |
|---|---|
| Upload a Knowledge Base `.txt` → `ready`; object at `ceopro-rag-knowledge/uploads/<tenant>/<sha256>.txt`; downloaded byte-identical; unsigned GET → 403 | PASS |
| Retry (re-reads the object from storage and re-indexes it) | PASS |
| Assistant for company A: the document's marked sentence reaches the model prompt and answer | PASS* |
| Company B: doesn't list A's document, retry on it → 404, assistant never receives it | PASS |
| Marketing image generated (designed poster) → stored under `<tenant>/<campaign>/`, served, repeat view → 304, B → 404 | PASS** |
| API restarted → the same image byte-identical and the document still ready | PASS |
| Ceiling just above use → upload refused **507** "File storage is full…", nothing stored; `/health/storage` shows % used | PASS |
| Endpoint unreachable → upload **503** "File storage is unavailable…"; `/health/storage` 503 in 0.4 s; `/health/ready` still 200 | PASS |

\* No language model runs locally and the hosted key was deliberately not used: the model was a **local mock** that
echoes prompt lines carrying the test marker. That proves retrieval from storage reached the model. It does not
test answer quality. \*\* The campaign row and its copy were inserted as a synthetic fixture (copy generation needs a
real model). Generating, storing and serving the image used the real API and storage path.

Automated: `test_object_storage.py` (offline + real MinIO), the new two-company summary regression test, the existing
MinIO-backed upload/summary/marketing tests. Full backend suite: see the PR. Frontend: 282/282 tests, lint clean.

## 3. Owner steps (one time, about 10 minutes, no card)

Keys go **only** into the Render dashboard, never into chat, email, Git or an agent environment.

1. Go to backblaze.com → **Sign Up** for B2 Cloud Storage. Use the KEEL owner email. Pick a region (choose
   **EU Central** if most customers are in Jordan/the Gulf; otherwise US West). Do **not** add a payment method.
2. **Caps & Alerts** (left menu, under B2 Cloud Storage): set **every** daily cap to **$0.00**: Storage,
   Download Bandwidth, Class B Transactions, Class C Transactions. Turn on email alerts. Click **Update**.
   (With $0 caps, B2 refuses anything beyond the free allowance instead of billing it.)
3. **Buckets → Create a Bucket**: name `keel-prod-files-<random 6 letters>` (names are global; lowercase,
   digits, hyphens). **Files in Bucket: Private**. Default encryption: **Enable** (SSE-B2). Object lock: off.
   Create it. Note the bucket's **Endpoint** shown on its card (e.g. `s3.eu-central-003.backblazeb2.com`).
4. **Lifecycle settings** for the bucket: "Keep only the last version of the file". Overwritten summaries then
   don't keep old versions that count toward the 10 GB.
5. **Application Keys → Add a New Application Key**: name `keel-production`; **Allow access to Bucket(s): only the
   bucket above**; Type of Access: **Read and Write**; leave "Allow List All Bucket names" off; no file-name prefix;
   no expiry. Click **Create**. The `keyID` and `applicationKey` are shown **once**.
6. Open Render → service `ceopro-ai-new` → **Environment**, and paste directly from the B2 page:

   | Variable | Value |
   |---|---|
   | `MINIO_ENDPOINT` | `https://` + the bucket's endpoint, e.g. `https://s3.eu-central-003.backblazeb2.com` |
   | `MINIO_BUCKET` | the bucket name |
   | `MINIO_ROOT_USER` | the `keyID` |
   | `MINIO_ROOT_PASSWORD` | the `applicationKey` |

   Save **without deploying** ("Save, rebuild and deploy" only if Session 1 asked you to). Tell Session 1 "storage
   variables saved". Never use the B2 master application key.

## 4. Deploy and verify (Session 1 deploys; Session 2 verifies)

Session 1, after this PR is merged and the owner has saved the variables:

1. Deploy the merged commit as usual (no migrations in this change). Optional variables keep their defaults:
   `STORAGE_QUOTA_BYTES=9000000000`, `STORAGE_MAX_OBJECT_BYTES=26214400`, `STORAGE_USAGE_TTL_SECONDS=600`.
2. Check the start-up log for config findings on `MINIO_*` / `STORAGE_*` (names only are logged).
3. `GET https://<api>/health/storage` → 200 `{"status":"ok","mode":"single_bucket", ...}`. `unavailable` with
   `StorageUnavailable` means a wrong key, bucket or endpoint; roll the variables back by deleting `MINIO_ENDPOINT`
   (storage then reads `not_configured` and everything else works as before).

Session 2 (read-only, a synthetic test company only):

1. `/health/storage` is `ok`.
2. Knowledge Base: upload a small synthetic `.txt`/`.pdf` → status `ready`; ask the assistant about a fact only in it
   → the answer cites it; it appears in the document list.
3. Marketing: generate a campaign image → it shows; reload after a redeploy/restart → it still shows (it is in
   B2, not on Render's disk); a second load returns 304.
4. Privacy: an unsigned `GET https://<endpoint>/<bucket>/` and a GET of any object return 403.
5. A second synthetic company cannot see the first company's document or image (404).
6. Delete the synthetic files/company afterwards.

## 5. Rollback

Delete `MINIO_ENDPOINT` in Render (or roll back the deploy). Uploads return "Document storage is unavailable"
again; nothing else is affected. Objects stay in the private bucket.

## 6. Known limits

- The 9 GB total is measured per process from a listing every 10 minutes plus that process's own writes, so
  several processes writing at the same time can pass it briefly. B2's $0 caps are the hard stop.
- B2 keeps earlier versions of overwritten or deleted files, and they count as stored data. The lifecycle rule in
  step 4 removes them after a day. KEEL's listing sees only current files, so for that day it slightly
  under-counts. The 1 GB margin below 10 GB covers this.
- 2,500 downloads/day is low for many active image viewers; beyond it images fail to load until the next day.
  If that happens regularly, a paid plan needs an owner decision (not made here).
- B2 has no per-tenant credentials. Tenant isolation is by key prefix plus KEEL's RLS-checked lookups. Objects are
  only ever served through the authenticated API, never by direct or signed URL.
