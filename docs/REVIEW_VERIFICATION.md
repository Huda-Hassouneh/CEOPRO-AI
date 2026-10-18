# Review verification — actual results

Executed in an isolated Linux workspace with Node 24.19.0 and Python 3.12. The user's Windows PostgreSQL, Redis, provider accounts and running processes were not accessible. No live credentials were used.

| Command / check | Observed result |
| --- | --- |
| Root `npm run build` | Node Prisma generation/TypeScript and frontend Vite build passed. Existing large-bundle warning remains. |
| Root `npm run test:competitor-boundary` | 7 backend tests + 2 frontend render/API-boundary tests passed; 170 team-file hashes/file-set parity passed. Includes full Prisma migration replay, suppressed autoqueue trigger, repeated migration, data retention and restricted-role tenant read isolation. |
| Root `npm run test:merge` | Passed: i18n, connected-data frontend checks and the new boundary gate. |
| Backend `npm run test:store-connectors` with `KEEL_TEST_PYTHON` pointing to the test environment | 12 passed. Includes Node → Python adapter → restricted PostgreSQL, WooCommerce/Shopify normalization, repeated sync/idempotency, canonical sales, inventory/invoice corrections and tenant/secret isolation using provider fixtures. This was not a real-store network test. |
| Backend `node --import tsx --test tests/business-recommendations/end-to-end.test.mjs` with `KEEL_TEST_PYTHON` | 1 passed: authenticated Node/Python HTTP, restricted DB, imported sales, evidence, notification dedupe, dismissal and outage retention. |
| Backend `npm run test:ai-pricing:integrity` | 15 + 22 + 9 + 2 tests passed (policy, PostgreSQL/HTTP/evidence, client/contracts and frontend evidence). |
| Backend `npm run test:demand-prediction:unit` | 56 passed. |
| Backend `npm run test:rag-integrity` | 5 policy/integrity/HTTP + 25 contract + 2 citation-render tests passed. |
| Backend `node --import tsx --test tests/rls/signup-rls-isolated.test.mjs` | 1 passed, including pre-fix 42P17 reproduction and repaired restricted-role/auth scenarios. Existing API has no refresh-token endpoint; test output states that limitation. |
| Backend `node --import tsx --test tests/notifications/important-events.test.ts tests/notifications/tenant/*.test.ts tests/notifications/platform/*.test.ts` | 35 passed. |
| Frontend `npm run test:i18n:render` | 40 passed, including store connection, pricing and RAG interface render tests. |
| Frontend `npm run verify:i18n` | Passed: 4,333 keys per language, 2,864 static calls and matching placeholders at run time. |
| Backend `node --test tests/handoff/*.test.mjs` from root | 2 passed: safe development setup/migration compatibility and restricted-role password provisioning. |
| Python `python -m pytest src/ai/connectors/tests -q` from `ai/` | 41 passed, including independent bounded gzip/plain decoder. |
| Python `python -m pytest tests/storage/test_summary_object_keys.py src/market_scraper/tests/test_network_security.py -q` | 9 passed. |
| Python `python -m pytest src/ai/tests/test_rag_structured_summaries_offline.py -q` | 4 passed after updating test-only tenant/slot fixtures to valid identifiers required by the retained isolation boundary. |
| Python syntax parsing | All 645 Python source files parsed. Existing invalid-escape SyntaxWarning in team extraction source remains unchanged. |
| Root `node scripts/verify-handoff.mjs` | Passed: 24 active integrated Markdown files, relative links, four environment examples and delegated scripts. Imported standalone team documentation is excluded explicitly. |

## Reproducing on Windows

From the extracted `keel` root after installing dependencies:

```powershell
npm.cmd run build
npm.cmd run test:merge
npm.cmd run verify:handoff

# Existing Python virtual environment with store + insights test dependencies:
$env:KEEL_TEST_PYTHON = (Resolve-Path .\ai\.venv\Scripts\python.exe).Path
npm.cmd --prefix backend run test:store-connectors
npm.cmd --prefix backend run test:rag-integrity
npm.cmd --prefix backend run test:rls:isolated
Push-Location .\ai
try {
    & .\.venv\Scripts\python.exe -m pytest src/ai/connectors/tests tests/storage/test_summary_object_keys.py src/market_scraper/tests/test_network_security.py src/ai/tests/test_rag_structured_summaries_offline.py -q
} finally { Pop-Location }
```

The Python fixture suites require pytest and the imported modules' dependencies; install appropriate project requirements in a separate test environment. No model weights were downloaded during these checks. First store test attempt lacked uvicorn in the default interpreter; rerunning with the configured test Python passed. First broader Python collection lacked document libraries; after installing them, the targeted offline RAG suite was run and passed. No production algorithm was changed to accommodate those environment failures.

## Explicitly unverified

- Your live KEEL_DEV migration status and production PostgreSQL behavior (isolated tests use PostgreSQL-compatible PGlite).
- Live WooCommerce/Shopify authorization, provider reachability, new orders and tunnel URLs after this source replacement.
- Entire standalone team Python migration chain, full API, all AI models, all competitor workers and their live network behavior.
- Existing custom competitor discovery/collection acceptance suites: deliberately withdrawn integration, retained historical tests, not claimed passing.
- Full repository-wide test suite, browser navigation, screenshot/viewport/accessibility testing, deployment, GitHub merge or publication.
