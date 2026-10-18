# Contributing

Read the root README, Architecture and Development guides first. Work within the relevant domain module and reuse its existing UI/API/repository patterns. Keep tenant context, permission and entitlement checks intact. Node owns billing and canonical data; Python adapters translate providers and should remain stateless.

Use forward Prisma SQL migrations for deployed schema changes. Never rewrite applied migration SQL, run migrate reset against shared data, or pre-load base-schema.sql before the baseline migration. Separate operator credentials from runtime test credentials.

A change should include a concise explanation, relevant verification results and any provider/data prerequisites. Prefer targeted behavior tests; distinguish source-contract tests, isolated PostgreSQL-compatible tests, real PostgreSQL restricted-role tests and live browser/provider tests. Do not label mocked/isolated results as a production check.

Before review run root build/test:merge and the affected feature's tests. For frontend text use existing English/Arabic dictionary keys, preserve interpolation and run translation/render checks. For stores verify idempotent stable external IDs, refunds, quantities/currency and tenant capacity. For workers keep truthful job/error status and bounded retries. Do not introduce duplicate consumers or additional auth/billing systems.

Commit safe examples, lockfiles and migration files. Do not commit local env files, credentials, node_modules, venvs, dist, test traces or database backups. Update the authoritative guide whose contract changed; avoid another temporary FIX/FINAL/STATUS Markdown file. docs/MARKDOWN_AUDIT.csv maps prior notes to the consolidated guides.
