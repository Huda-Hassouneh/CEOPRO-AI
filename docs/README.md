# Developer documentation

Start at the [root README](../README.md). These guides describe the current
Python/React application; no knowledge of previous integration work is required.

## Everyday development

| What you need | Authoritative guide |
|---|---|
| Install, start, sign up, stop and debug | [Running KEEL locally](LOCAL_DEVELOPMENT.md) |
| Understand request/data flows and security boundaries | [Architecture](ARCHITECTURE.md) |
| Find feature code, inputs, rules and limits | [Features](FEATURES.md) |
| Configure generated settings and optional keys | [Environment configuration](ENVIRONMENT_VARIABLES.md) |
| Change schema, inspect roles and initialize approved catalogs | [Database and migrations](DATABASE.md) |
| Configure Stripe, AI, Shopify, WooCommerce or email | [Integrations](INTEGRATIONS.md) |
| Find worker entrypoints, health evidence and retries | [Workers](WORKERS.md) |
| Run offline, native database and browser checks | [Testing](TESTING.md) |
| Diagnose local failures | [Troubleshooting](TROUBLESHOOTING.md) |
| Contribute a scoped, verified change | [Contributing](CONTRIBUTING.md) |

Component references: [Python backend](../backend/README.md),
[React frontend](../frontend/README.md), [AI services](../backend/src/ai/README.md).
The existing local-development guide is the getting-started authority; there
is no competing setup guide to keep synchronized.

## Maintainer and operator references

- [Subscriptions, Credits and payment rules](SUBSCRIPTIONS_AND_CREDITS.md)
- [Provider keys/accounts](../backend/KEYS_AND_ACCOUNTS_NEEDED.md) and
  [source-linked environment inventory](reference/ENVIRONMENT_INVENTORY.md)
- [Data ownership and contracts](../backend/src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md)
- [Collection and commerce internals](../backend/src/market_scraper/README.md)
- [Restricted billing database roles](CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md)
- [Local-only Stripe Test Clock](STRIPE_TEST_CLOCK_LOCAL_GUIDE.md)
- [Interrupted test-environment recovery](TEST_ENVIRONMENT_RECOVERY.md)
- [Measured onboarding, documentation inventory and PR limitations](REPOSITORY_READINESS.md)

## Historical decisions and evidence

Historical reports preserve what was approved or measured at a particular
revision/date. Their earlier test counts, ports, migration totals and readiness
verdicts are not current setup instructions.

- [Architecture/business decision register](keel-integration/DECISION_REGISTER.md)
  and its linked decision records preserve identity, payment, entitlement,
  privacy and accounting invariants. Read the explanation, not only the identifier.
- [Integration record index](keel-integration/README.md), `archive/`,
  `remediation/` and dated backend reports retain traceability and audit evidence.
- [Synthetic seed manifest](DEMO_SEED_PHASE1.md),
  [customer acceptance findings](DEMO_PHASE2_ACCEPTANCE.md) and
  [confirmed-defect remediation](DEMO_PHASE3_REMEDIATION.md) describe the existing
  meeting fixture; they are not required for ordinary development.
- [Codespaces](../CODESPACES_DEVELOPMENT.md),
  [earlier local harness](../RUNNING_LOCALLY.md) and
  [staging deployment](../STAGING_DEPLOYMENT.md) are environment-specific
  references. The native setup commands above are the teammate onboarding path.

No historical security decision, migration or acceptance evidence was removed.
Permanent coding-agent rules remain in [AGENTS.md](../AGENTS.md); human developers
do not need that file to start the application.
