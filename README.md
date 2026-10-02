# CEOPRO AI Backend

This repository is the backend for **CEOPRO AI**, a multi-tenant SaaS platform that combines subscription/billing management with business analytics, competitor intelligence, forecasting, document ingestion, RAG, sentiment analysis, market perception, and AI-assisted pricing.

I keep this backend responsible for the things that must stay authoritative on the server: tenant isolation, permissions, entitlements, usage limits, billing rules, pricing inputs, database persistence, and validation of external-service responses.

The codebase is written in **TypeScript** on **Node.js + Express**, uses **PostgreSQL + Prisma**, uses **Stripe** for the active payment-provider integration, and calls the CEOPRO AI service for selected AI workflows.

---

## Start here

If you are new to this repository, read the docs in this order:

1. **This README** — what the repo is and how to run it.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how I structure the backend and where responsibilities belong.
3. [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — the currently mounted HTTP routes and their access rules.
4. [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) — Stripe, AI-service, worker/trigger, database, and integration boundaries.
5. [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — what I have done, what I am doing now, what is next, and open decisions.

These files are intended to be the **canonical documentation set**. Older endpoint-by-endpoint notes and scattered module READMEs should not be treated as the source of truth once this documentation set is adopted.

---

## What this backend owns

The backend currently covers these main areas:

- Authentication/session support and tenant membership validation.
- Platform owner/admin operations.
- Subscription plans, checkout, plan changes, cancellation, invoices, promo codes, and Stripe webhooks.
- Custom-plan configuration, quotes, automatic/manual review flows, vendor rates, infrastructure rates, and pricing policy.
- Feature catalog, plan-feature assignments, entitlements, and metered usage.
- Dashboard aggregation.
- Competitor management and opportunity/leaderboard data.
- Market intelligence.
- Demand forecasting data.
- Data connections and business-data ingestion.
- RAG document/query flows.
- AI pricing recommendation.
- Sentiment analysis.
- Market Perception Index (MPI).

The backend deliberately keeps external AI/provider calls behind domain clients. External services do not own tenant authorization, billing decisions, or CEOPRO database rules.

---

## Tech stack

| Area                | Technology                                     |
| ------------------- | ---------------------------------------------- |
| Runtime             | Node.js                                        |
| Language            | TypeScript                                     |
| HTTP                | Express 5                                      |
| Database            | PostgreSQL 17                                  |
| Vector support      | pgvector                                       |
| ORM                 | Prisma 7                                       |
| Validation          | Zod                                            |
| Authentication      | JWT                                            |
| Payments            | Stripe                                         |
| Uploads             | Multer                                         |
| Spreadsheet parsing | xlsx                                           |
| Testing             | Node test runner + custom verification scripts |

---

## Repository layout

```text
.
├── prisma/
│   ├── schema.prisma
│   ├── migrations/
│   ├── bootstrap/
│   └── seed*.ts
├── scripts/
├── src/
│   ├── config/
│   ├── constants/
│   ├── errors/
│   ├── middleware/
│   ├── modules/
│   │   ├── subscription/
│   │   ├── features/
│   │   ├── platform-admin/
│   │   ├── owner-portal/
│   │   ├── dashboard/
│   │   ├── competitors/
│   │   ├── opportunities/
│   │   ├── dataconnection/
│   │   ├── forecasting/
│   │   ├── market-intelligence/
│   │   ├── pricing/
│   │   ├── sentiment/
│   │   ├── mpi/
│   │   └── auth/
│   ├── types/
│   ├── utils/
│   ├── validators/
│   ├── app.ts
│   └── server.ts
├── tests/
├── docker-compose.yaml
├── package.json
├── prisma7.config.ts
└── tsconfig.json
```

My preferred feature-domain shape is:

```text
<feature-domain>/
├── index.ts
├── route/
├── controller/
├── service/
├── repo/        # only when the feature owns persistence
├── client/      # only when the feature owns an external integration
└── types/
```

I do not create empty layers just to make every folder look identical. The responsibility matters more than the folder count.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detailed rules.

---

## Local requirements

Install:

- Node.js compatible with the versions used by this project.
- npm.
- Docker Desktop or another Docker runtime, if you want to use the included PostgreSQL container.
- PostgreSQL directly, if you do not use Docker.
- Stripe test credentials for billing flows.
- The CEOPRO AI service, or local AI mocks where supported.

---

## 1. Install dependencies

For a normal development install:

```bash
npm install
```

For a clean reproducible install from the lockfile:

```bash
npm ci
```

---

## 2. Start PostgreSQL

The included Compose file runs PostgreSQL with pgvector:

```bash
docker compose up -d postgres
```

Current local container settings:

```text
Image:      pgvector/pgvector:0.8.6-pg17
Database:   CEOPROTEST3
Host:       127.0.0.1
Host port:  5433
DB port:    5432
User:       postgres
```

`POSTGRES_PASSWORD` is supplied through the environment.

Check the container:

```bash
docker compose ps
```

---

## 3. Configure the environment

This repository uses `.env` by default. I keep real credentials local and do not document or commit secret values.

At minimum, a normal local environment needs the database/JWT values and, depending on the flow being tested, Stripe and AI values.

Example shape:

```env
PORT=5000

POSTGRES_PASSWORD=...
DATABASE_URL=postgresql://postgres:...@127.0.0.1:5433/CEOPROTEST3

JWT_SECRET=...
JWT_REFRESH_SECRET=...
JWT_ACCESS_EXPIRES_IN=1h
JWT_REFRESH_EXPIRES_IN=7d

CORS_ORIGINS=http://localhost:5173
JSON_BODY_LIMIT=1mb
MAX_UPLOAD_BYTES=10485760

STRIPE_SECRET_KEY=...
STRIPE_SECRET_WEBHOOK=...
SUCCESS_SUBSCRIPTION_URL=http://localhost:5173
FAILED_SUBSCRIPTION_URL=http://localhost:5173
PROMO_FIXED_AMOUNT_CURRENCY=USD

AI_SERVICE_URL=http://localhost:8000
AI_SERVICE_USE_MOCKS=true
```

Other environment values are used by bootstrap/test utilities:

```text
OWNER_EMAIL
OWNER_PASSWORD
OWNER_FULL_NAME
OWNER_COMPANY_NAME
OWNER_COUNTRY_CODE
OWNER_PRIMARY_CURRENCY
OWNER_TIMEZONE
OWNER_LANGUAGE

ADMIN_EMAIL
ADMIN_PASSWORD
ADMIN_FULL_NAME
ADMIN_TENANT_ID
ADMIN_LANGUAGE

SEED_DEV_PASSWORD
DASHBOARD_TEST_TENANT_ID
DASHBOARD_TEST_PERIOD_DAYS
ALLOW_PRODUCTION_FEATURE_BOOTSTRAP

STRIPE_USE_TEST_CLOCK
STRIPE_TEST_CLOCK_ID
```

Important: the source snapshot may contain a local `.env`, but documentation must never copy those values. Keep `.env` outside version control and rotate any credential that has ever been exposed.

---

## 4. Generate Prisma Client

```bash
npm run prisma:generate
```

Validate the Prisma schema:

```bash
npm run prisma:validate
```

---

## 5. Apply database migrations

For an existing/shared environment:

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

For local migration development, use Prisma's development workflow intentionally rather than applying ad-hoc schema changes.

The database requires pgvector because the schema contains RAG/vector-related data.

---

## 6. Bootstrap data when needed

### Platform owner

Set the `OWNER_*` environment values first:

```bash
npm run bootstrap:owner
```

This creates/reuses the platform company, creates/reuses the owner user, attaches the `owner` role, and prints a development access token.

### Platform admin

Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_TENANT_ID`:

```bash
npm run bootstrap:admin
```

### Canonical feature catalog

```bash
npm run bootstrap:features
```

This command is intentionally guarded in production because it rebuilds the canonical feature catalog and restores related links.

### Stripe product bootstrap

```bash
npm run bootstrap:stripe
```

This reuses the normal onboarding service and stores the shared Stripe product identifier in application configuration.

### Development seed

```bash
npm run prisma:seed
```

The seed has safety checks and is intended for development/test databases, not an arbitrary production database.

---

## 7. Run the backend

Development with watch mode:

```bash
npm run dev
```

Default server origin:

```text
http://localhost:5000
```

Basic health response:

```http
GET /
```

Production build:

```bash
npm run build
npm start
```

---

## Useful commands

| Command                      | What I use it for                                          |
| ---------------------------- | ---------------------------------------------------------- |
| `npm run dev`                | Run the TypeScript server in watch mode                    |
| `npm run build`              | Generate Prisma Client and compile TypeScript              |
| `npm start`                  | Run the compiled server from `dist/`                       |
| `npm test`                   | Run unit + route + security + custom-plan + feature checks |
| `npm run validate`           | Prisma validation + build + complete test suite            |
| `npm run prisma:generate`    | Generate Prisma Client                                     |
| `npm run prisma:validate`    | Validate Prisma schema/config                              |
| `npm run prisma:seed`        | Seed development/test data                                 |
| `npm run bootstrap:owner`    | Bootstrap the platform owner                               |
| `npm run bootstrap:admin`    | Bootstrap an admin membership                              |
| `npm run bootstrap:features` | Rebuild the canonical feature catalog                      |
| `npm run bootstrap:stripe`   | Initialize the shared Stripe product                       |
| `npm run dev:token`          | Generate the developer mock token configured by the script |

Before merging or deploying backend changes, my preferred local check is:

```bash
npm ci
npm run validate
```

**Current snapshot note:** two source-contract verification scripts still need to be synchronized with the recent domain refactor, so `npm run validate` is expected to remain red until those script expectations are updated without weakening the checks. I track the exact mismatches in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).

Then I test any external integration I changed against its real test environment.

---

## Authentication and authorization model

Most tenant routes expect:

```http
Authorization: Bearer <JWT>
```

The backend then resolves the tenant from the token and verifies the active tenant membership.

There are two main authorization layers:

- **Tenant permissions**, such as `manage_billing`.
- **Platform permissions**, such as `billing.read`, `billing.manage`, and `billing.pricing.manage`.

Feature operations may additionally require a feature entitlement or feature-access check.

The backend is the authority here. The frontend can hide/show UI, but it must not be the security boundary.

---

## Important runtime rules

### Stripe webhook body must stay raw

`/stripe/webhooks` is mounted **before** `express.json()`.

Do not move it behind the JSON body parser. Stripe signature verification requires the untouched request body.

### AI mocks are development behavior

Some AI clients support:

```env
AI_SERVICE_USE_MOCKS=true
```

Production should use the real AI service and should not silently fall back to fake data.

### Missing analytical data is not zero

Forecasting, market-intelligence, sentiment, and MPI flows intentionally preserve unavailable/unknown states when source data is incomplete. I do not want missing data to be converted into believable-looking production numbers.

### The auth module exists but is not currently mounted

`src/modules/auth` contains login/session/logout/invitation routes, but the current `src/app.ts` does not mount that router. Those endpoints are therefore **not part of the live route table** until I explicitly mount them.

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

---

## Documentation policy

I want the repo documentation to answer five questions quickly:

1. What is this backend?
2. How do I run it?
3. How is it structured?
4. What API does it expose?
5. What is finished, what is in progress, and what comes next?

If implementation changes affect one of those answers, I update the relevant canonical doc instead of adding another one-off Markdown file.
