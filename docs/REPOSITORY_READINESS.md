# Developer onboarding and repository readiness

Recorded **2026-10-28**. **Windows core onboarding: PASS. Future PR readiness:
PARTIAL.** Documentation/setup work is complete for the measured scope; this is
not full product acceptance, a production deployment certificate or a merge
conflict check against current GitHub `main`.

## Scope and source

Branch: `integration/keel-full-migration`. Starting/runtime verification source:
`ed1246c50090b38a6cdd32c54898b671f03fa297`. The local cleanup commit carrying
this report changes documentation, public examples and ignore rules only;
no application/worker logic, dependencies or migrations were changed. Use
`git log -1 --oneline` and `git status --short` for the delivered commit/state.

Verification used a **local-only clone** of that committed source:

```powershell
git clone --local --no-hardlinks --single-branch --branch integration/keel-full-migration --no-tags . .dev/onboarding-checkout
```

It installed its own dependencies and generated new credentials, project,
database, ports and volumes. No original `.dev` fixture or provider key was
copied. Public documentation/template updates are independent of runtime
behavior; the tested setup commands match the revised guides. No remote Git
operation, main modification, deployment, paid AI call, Stripe operation or
normal application restart was performed.

## Exact teammate path

After obtaining the team's checkout and selecting the intended development
branch, run from its root in Windows PowerShell:

```powershell
python --version
node --version
npm --version
docker info
docker compose version
.\dev.ps1 setup
.\dev.ps1 up --mode full
.\dev.ps1 status
```

Open the printed frontend URL, sign up, verify the code in the printed Mailpit
inbox and complete onboarding. Core setup requires no environment-file copy or
external account. Use [the setup checklist](LOCAL_DEVELOPMENT.md#teammate-onboarding-checklist)
and [optional integration configuration](INTEGRATIONS.md). Stop with
`dev.ps1 down`; retained config/volumes support the next `up`.

## Fresh-checkout verification

Measured tools: Windows PowerShell **5.1.26100.9711**, CPython **3.12.7**,
Node **24.22.0**, npm **11.19.1**, Docker **29.8.0**, Compose **5.5.1**.
Commands below ran through `.dev/onboarding-checkout/dev.ps1`; paths shown in
the table are relative to that disposable checkout unless stated otherwise.

| Step / actual command or check | Result | Expected versus actual / evidence |
|---|---|---|
| Local source clone, no inherited private state | PASS | New checkout/config/DB; zero companies before synthetic signup. |
| `setup` | PASS | New venv, constrained core pip installation, `pip check`: no broken requirements; `npm ci`: 306 packages installed, zero npm-reported vulnerabilities. Package caches were allowed; no shared venv/node_modules was used. |
| Repeat `setup` | PASS | Existing generated config/dependency markers reused without a dependency-install step or account reset. |
| `up --mode full` | PASS | API, Vite, eight workers and four healthy infrastructure containers. |
| Fresh migrations / catalogs | PASS | 147 migrations; 120 FORCE RLS tables, restricted password login, feature catalog, four current plan keys and approved Groq input/output schedules. No initial customer/business seed. |
| Repeat `up --mode full` | PASS | Owned processes retained; migration log applied **0** new migrations. |
| `doctor`, `status` | PASS | Database/Redis readiness, all eight worker checks, frontend proxy and actual selected ports. |
| `test --suite frontend` | PASS | **230 tests, zero failures**, ESLint and production build; root wrapper also passed **52 tooling tests**. Existing large-chunk/dynamic-import warnings and ESLint package deprecation warning remain. |
| `test --suite database` | PASS | New disposable test DB, fresh/repeat migrations and **18 native RLS tests**, no skips reported. |
| `test --suite browser` | PASS | Actual Chrome English/Arabic login/signup rendering, mobile RTL, API proxy/plans, unauthenticated owner denial; no response mocks. |
| Real HTTP signup / SMTP / verification / login | PASS | **16 checks**: actual Mailpit-delivered code, verified session, empty isolated catalog, eligible normal trial and Tenant Owner denied platform access. No verification shortcut. |
| Authenticated browser after restart | PASS | English 1440px and Arabic 390px login into that same new tenant; no page errors or horizontal overflow; private screenshots. |
| `restart --mode full` | PASS | Same account/tenant still logs in. Seven financial/provider schedule/policy table fingerprints unchanged before versus after repeat-up/restart. |
| Missing optional integrations | PASS, bounded | Startup reports Groq/Stripe/Shopify/search unavailable and Test Clock disabled; no fake provider success. Actual external requests were not acceptance-tested. |
| `down` | PASS | Only disposable checkout processes/containers stopped; its volumes, database, account and evidence retained. Original stack remains running. |
| Environment inventory | PASS | Regenerated from current production source and `environment_inventory.py --check` passes; source parsing emits an existing invalid-escape SyntaxWarning. |
| Local documentation links | PASS | **1,069** local file/heading links checked across **165** Markdown files, including repaired archive/RAG links; zero missing targets/anchors. External URLs are reference links, not an exhaustive availability test. |
| Current tracked-file credential scan / ignore checks | PASS, bounded | No provider-key/private-key signatures, tracked private environment/account/dump files or tracked files accidentally matched by ignore rules. Pattern scanning is not a full secret/security certification. |
| Full backend selection, models/weights, live providers/payment/store acceptance | NOT TESTED | Native RLS and existing scoped historical evidence are not substitutes for the full suites. No paid resources were used. |
| Python 3.11, Linux/macOS and production install | NOT TESTED | Shared entrypoints and production bootstrap were source-reviewed; only the Windows/Python 3.12 core path was executed here. |
| Latest remote `main` compatibility | NOT TESTED | No fetch/pull, merge, rebase or remote PR operation. |

Private evidence is retained under `.dev/evidence/repository-readiness/`:
`fresh-setup.log`, `fresh-repeat-setup.log`, `fresh-up.log`,
`fresh-repeat-up.log`, `fresh-restart.log`, `fresh-doctor.log`,
`fresh-status.log`, `fresh-frontend-tests.log`, `fresh-database-tests.log`,
`fresh-browser.log`, `fresh-http.json`, `fresh-authenticated-browser.json`,
`fresh-authenticated-*.png`, `fresh-persistence.json`, `fresh-down.log` and
`original-runtime-final.log`; `final-repository-audit.json` records link/scan
results. Public-browser screenshots/results and retained
test DB names also live in the disposable checkout's own private `.dev/`.
These generated records, credentials and logs are intentionally not committed.
An additional values-free `credential-uri-audit.json` records URL-pattern
locations; these include source interpolation, documented placeholders,
ephemeral CI credentials and tutorial defaults, not evidence of real provider
access. No JWT or additional hosted-provider key signatures were found.

## Existing demo observation — no repair performed

A read-only check of the original configured DB found **361 invoices, 1,801
invoice items, 1,800 transactions, 1,003 competitors and 25 price observations**.
The historical manifest expects 360 / 1,800 / 1,800 / 3 / 24 respectively.
Ten active products remain. Original `DEMO-` numbered paid invoices still total
**JOD 85,892.200**; all current paid invoices total **JOD 85,912.200**.

The latest invoice creation timestamp is **16:22:11 UTC**, before the isolated
clone was created at **18:42:50 UTC**. This establishes that the extra invoice
predates this onboarding verification; the origin of the additional competitor
and price records is not established here. Do not assume that this cleanup or
a particular earlier test caused them. Exact historical-manifest reconciliation
is **FAIL**, while the existing records remain preserved as found. No reseed,
deletion, classification cleanup or financial restoration was attempted.
Evidence: private `original-demo-readonly.json`.

The original DB remains at **146/147** applied migrations: approved AI pricing
migration `20261115000000_approved_ai_provider_pricing_v1.sql` is still pending.
It was not silently applied to that DB. The original API launch revision remains
`fa9a18a7`; frontend/workers retain their prior launch ledger. Healthy original
services were not restarted. A later explicitly chosen startup/migrate will run
pending migrations through the normal installation authority.

## Documentation cleanup decisions

- **Improved:** root README and documentation index; setup, architecture,
  database, environment, integrations, workers and troubleshooting guides;
  component/AI navigation and safe public environment examples.
- **Added because missing:** one feature map, one testing guide and this combined
  inventory/verification/readiness report. The existing local-development guide
  remains the getting-started authority; no duplicate `GETTING_STARTED.md`.
- **Consolidated navigation:** primary test selection now lives in `TESTING.md`;
  environment generation is explained once in the setup/configuration guides;
  historical recovery and integration reports are secondary references.
- **Historical records preserved:** all original Markdown files, approved
  decisions, security/billing evidence, seed manifests and acceptance reports.
  `CURRENT_STATUS.md` and the old integration index now identify their historical
  scope rather than presenting old verdicts as current status. Permanent agent
  rules retain security invariants and no longer require a personal checkout path.
- **Links fixed:** two relative links in the archived backend README and the
  stale RAG overview anchor; primary navigation now points to the actual root
  Codespaces/staging guides. Regenerated environment links reflect current lines.
- **Removed/renamed:** none. No exact duplicate Markdown content was found.
  Overlap was addressed by navigation and scope, not deleting audit evidence.
- **Ignore coverage:** added private environment variants, virtualenv/cache paths,
  private account JSON and dumps. Examples and every existing tracked source
  remain visible. Legitimate assets, XLSX templates/fixtures and dated evidence
  logs were retained, not treated as disposable solely by extension/size.

## Future PR limits and maintainer follow-up

At inspection, local `main` was `041f9f24`, an ancestor **173 commits behind**
the starting integration HEAD, with zero main-only commits. This cleanup adds
one local commit. Local cached tracking refs are not current GitHub evidence.
No claim is made that the latest remote branch is conflict-free or merge-ready.

Before a future PR/release, the maintainer should:

- Review the local diff and run the broader affected suites/organization checks.
  Documentation readiness does not certify all 15 customer workflows.
- Confirm historical secret rotation. Local history shows root `.env` was added
  in `128dba29` and removed in `4c5536e0` on 2026-10-19; current-file exclusion
  cannot prove those old credentials were revoked. Values were not displayed,
  rewritten or copied. Rotation assurance is **NOT VERIFIED**; follow
  [credential-rotation guidance](SECURITY_CREDENTIAL_ROTATION.md).
- Investigate the active-demo manifest mismatch independently before claiming
  the original meeting totals describe all current rows. This task deliberately
  preserves the active dataset and financial records.
- Treat `docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md` as historical
  evidence: it contains a pre-existing non-UTF-8 byte. It was inventoried using
  tolerant decoding, left byte-for-byte unchanged, and excluded from any claim
  that every historical file has been normalized to UTF-8.
- Perform remote synchronization/conflict review through the user's own workflow.
  No remote or deployment action is authorized by this report.

## Complete Markdown inventory

Snapshot categories below describe purpose, not blanket acceptance of every
historical statement. **Primary** = current developer entry point;
**Reference** = useful technical/operator/approved-decision material;
**History** = dated design/security/verification evidence;
**Outdated guidance** = retained older workflow, superseded for ordinary setup;
**Working note** = retained historical planning/draft, not the current task queue.
No file was classified for deletion or as an unnecessary generated document.

<!-- DOCUMENTATION_INVENTORY -->

Inventoried **165 Markdown files** (162 pre-existing; three added). History: **73**; Outdated guidance: **2**; Primary: **14**; Reference: **70**; Working note: **6**.

<details>
<summary>Every Markdown file and its retention decision</summary>

| File | Classification | Decision / purpose |
|---|---|---|
| [.github/pull_request_template.md](../.github/pull_request_template.md) | Reference | Retain technical/operator or approved-decision reference |
| [AGENTS.md](../AGENTS.md) | Reference | Permanent agent instructions; portable authority, invariants retained |
| [CODESPACES_DEVELOPMENT.md](../CODESPACES_DEVELOPMENT.md) | Reference | Retain technical/operator or approved-decision reference |
| [CURRENT_STATUS.md](../CURRENT_STATUS.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [README.md](../README.md) | Primary | Current developer guide; improved or retained |
| [RUNNING_LOCALLY.md](../RUNNING_LOCALLY.md) | Outdated guidance | Retain older workflow; use current setup/database guide |
| [STAGING_DEPLOYMENT.md](../STAGING_DEPLOYMENT.md) | Reference | Retain technical/operator or approved-decision reference |
| [SUBSCRIPTION_REMEDIATION_REPORT.md](../SUBSCRIPTION_REMEDIATION_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [backend/AI_ENGINEERING_PLAN.md](../backend/AI_ENGINEERING_PLAN.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/AI_PLAN_AND_CONTRACT_UPDATES.md](../backend/AI_PLAN_AND_CONTRACT_UPDATES.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/AI_PROGRESS.md](../backend/AI_PROGRESS.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/COMPETITOR_COMMENTS_AND_RETRY_PLAN.md](../backend/COMPETITOR_COMMENTS_AND_RETRY_PLAN.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/COMPETITOR_DATA_COMPLETENESS_PLAN.md](../backend/COMPETITOR_DATA_COMPLETENESS_PLAN.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/KEYS_AND_ACCOUNTS_NEEDED.md](../backend/KEYS_AND_ACCOUNTS_NEEDED.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/MARKETING_AI_CAPABILITIES.md](../backend/MARKETING_AI_CAPABILITIES.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/MARKET_DATA_PRIVACY_AND_RETENTION.md](../backend/MARKET_DATA_PRIVACY_AND_RETENTION.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/MASTER_SPEC_v4.md](../backend/MASTER_SPEC_v4.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/MIGRATIONS_TO_APPLY.md](../backend/MIGRATIONS_TO_APPLY.md) | Outdated guidance | Retain older workflow; use current setup/database guide |
| [backend/PENDING_ACTIONS.md](../backend/PENDING_ACTIONS.md) | Working note | Preserve historical planning context; not the current task queue |
| [backend/POS_ERP_SYSTEMS.md](../backend/POS_ERP_SYSTEMS.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/PRICE_COMPARISON_ACCURACY_PLAN.md](../backend/PRICE_COMPARISON_ACCURACY_PLAN.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/PRICE_COMPARISON_TIERS_PLAN.md](../backend/PRICE_COMPARISON_TIERS_PLAN.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/PR_DESCRIPTION_DRAFT.md](../backend/PR_DESCRIPTION_DRAFT.md) | Working note | Preserve historical planning context; not the current task queue |
| [backend/QA_TEST_REPORT.md](../backend/QA_TEST_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [backend/QA_TEST_STRATEGY.md](../backend/QA_TEST_STRATEGY.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/RAG_BUSINESS_COPILOT_ARCHITECTURE.md](../backend/RAG_BUSINESS_COPILOT_ARCHITECTURE.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/README.md](../backend/README.md) | Primary | Current developer guide; improved or retained |
| [backend/RED_FLAGS.md](../backend/RED_FLAGS.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/SECRETS_ROTATION_POLICY.md](../backend/SECRETS_ROTATION_POLICY.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/docs/BILLING_RUNTIME_ORIGIN_AND_CHECKOUT.md](../backend/docs/BILLING_RUNTIME_ORIGIN_AND_CHECKOUT.md) | Reference | Retain domain/design reference; verify claims against source |
| [backend/scripts/demo_companies/README.md](../backend/scripts/demo_companies/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/scripts/pentest/README.md](../backend/scripts/pentest/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/ai/README.md](../backend/src/ai/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/ai/extraction/SCALING.md](../backend/src/ai/extraction/SCALING.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/ai/forecasting/README.md](../backend/src/ai/forecasting/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/ai/rag/README.md](../backend/src/ai/rag/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/infrastructure/CONTRACT_CHANGELOG.md](../backend/src/infrastructure/CONTRACT_CHANGELOG.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md](../backend/src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/infrastructure/MINIO_STORAGE_ARCHITECTURE.md](../backend/src/infrastructure/MINIO_STORAGE_ARCHITECTURE.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/infrastructure/REDIS_ARCHITECTURE.md](../backend/src/infrastructure/REDIS_ARCHITECTURE.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/src/market_scraper/README.md](../backend/src/market_scraper/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [backend/templates/README.md](../backend/templates/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [design/liquid-glass/README.md](../design/liquid-glass/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/ACCOUNT_ONBOARDING_IDENTITY_FIX.md](ACCOUNT_ONBOARDING_IDENTITY_FIX.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/AI_MODEL_MARKETING_IMPLEMENTATION.md](AI_MODEL_MARKETING_IMPLEMENTATION.md) | Reference | Retain domain/design reference; verify claims against source |
| [docs/APIFY_DISCOVERY.md](APIFY_DISCOVERY.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | Primary | Current developer guide; improved or retained |
| [docs/ASSISTANT_QA_HANDOFF.md](ASSISTANT_QA_HANDOFF.md) | Working note | Preserve historical planning context; not the current task queue |
| [docs/CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md](CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md) | Reference | Retain domain/design reference; verify claims against source |
| [docs/CI_REPAIR.md](CI_REPAIR.md) | Reference | Retain domain/design reference; verify claims against source |
| [docs/CONTRIBUTING.md](CONTRIBUTING.md) | Primary | Current developer guide; improved or retained |
| [docs/DATABASE.md](DATABASE.md) | Primary | Current developer guide; improved or retained |
| [docs/DEMO_PHASE2_ACCEPTANCE.md](DEMO_PHASE2_ACCEPTANCE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/DEMO_PHASE3_REMEDIATION.md](DEMO_PHASE3_REMEDIATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/DEMO_SEED_PHASE1.md](DEMO_SEED_PHASE1.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/DEVELOPER_EXPERIENCE_VERIFICATION.md](DEVELOPER_EXPERIENCE_VERIFICATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | Primary | Current developer guide; improved or retained |
| [docs/FEATURES.md](FEATURES.md) | Primary | Current developer guide; improved or retained |
| [docs/FINAL_SYSTEM_AUDIT.md](FINAL_SYSTEM_AUDIT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/INTEGRATIONS.md](INTEGRATIONS.md) | Primary | Current developer guide; improved or retained |
| [docs/LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) | Primary | Current developer guide; improved or retained |
| [docs/PLAN_LIMITS_FEASIBILITY.md](PLAN_LIMITS_FEASIBILITY.md) | Reference | Retain domain/design reference; verify claims against source |
| [docs/PLATFORM_BILLING_LEGACY_PARITY_REPORT.md](PLATFORM_BILLING_LEGACY_PARITY_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/RAG_ASSISTANT_503_FIX.md](RAG_ASSISTANT_503_FIX.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/README.md](README.md) | Primary | Current developer guide; improved or retained |
| [docs/REPOSITORY_READINESS.md](REPOSITORY_READINESS.md) | History | This dated inventory and measured readiness record |
| [docs/SECRETS.md](SECRETS.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/SECURITY_CREDENTIAL_ROTATION.md](SECURITY_CREDENTIAL_ROTATION.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/SECURITY_PENTEST.md](SECURITY_PENTEST.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/STAGING_BILLING_RUNBOOK.md](STAGING_BILLING_RUNBOOK.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/STRIPE_TEST_CLOCK_LOCAL_GUIDE.md](STRIPE_TEST_CLOCK_LOCAL_GUIDE.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/SUBSCRIPTIONS_AND_CREDITS.md](SUBSCRIPTIONS_AND_CREDITS.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/TESTING.md](TESTING.md) | Primary | Current developer guide; improved or retained |
| [docs/TEST_ENVIRONMENT_RECOVERY.md](TEST_ENVIRONMENT_RECOVERY.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/TRIAL_DOWNGRADE_INTEGRITY_FIX.md](TRIAL_DOWNGRADE_INTEGRITY_FIX.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Primary | Current developer guide; improved or retained |
| [docs/WORKERS.md](WORKERS.md) | Primary | Current developer guide; improved or retained |
| [docs/ZERO_COST_IMAGE_GENERATION.md](ZERO_COST_IMAGE_GENERATION.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/archive/BACKEND_PHASE1_README.md](archive/BACKEND_PHASE1_README.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/archive/COMPLETENESS_MATRIX_HISTORY.md](archive/COMPLETENESS_MATRIX_HISTORY.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/archive/REFERENCE_PROJECT_COMPLETION_REPORT.md](archive/REFERENCE_PROJECT_COMPLETION_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/archive/STATUS_HISTORY.md](archive/STATUS_HISTORY.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/COVERAGE_RECONCILIATION.md](keel-integration/COVERAGE_RECONCILIATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/DECISION_REGISTER.md](keel-integration/DECISION_REGISTER.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/DEPENDENCY_AND_SCHEMA_MAP.md](keel-integration/DEPENDENCY_AND_SCHEMA_MAP.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/DOMAIN_READINESS.md](keel-integration/DOMAIN_READINESS.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/FEATURE_INVENTORY.md](keel-integration/FEATURE_INVENTORY.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/IMPLEMENTATION_PHASES.md](keel-integration/IMPLEMENTATION_PHASES.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/NEXT_IMPLEMENTATION_HANDOFF.md](keel-integration/NEXT_IMPLEMENTATION_HANDOFF.md) | Working note | Preserve historical planning context; not the current task queue |
| [docs/keel-integration/NEXT_TASK.md](keel-integration/NEXT_TASK.md) | Working note | Preserve historical planning context; not the current task queue |
| [docs/keel-integration/OPEN_GAPS_AND_RELEASE_BLOCKERS.md](keel-integration/OPEN_GAPS_AND_RELEASE_BLOCKERS.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/OWNER_APPROVAL_RECONCILIATION.md](keel-integration/OWNER_APPROVAL_RECONCILIATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/OWNER_DECISION_WORKSHEET.md](keel-integration/OWNER_DECISION_WORKSHEET.md) | Working note | Preserve historical planning context; not the current task queue |
| [docs/keel-integration/OWNER_RECONCILIATION_REPORT.md](keel-integration/OWNER_RECONCILIATION_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE0R_FINAL_REPORT.md](keel-integration/PHASE0R_FINAL_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE0R_README.md](keel-integration/PHASE0R_README.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE0V_FINAL_REPORT.md](keel-integration/PHASE0V_FINAL_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE0V_NATIVE_VERIFICATION.md](keel-integration/PHASE0V_NATIVE_VERIFICATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE0_FINAL_REPORT.md](keel-integration/PHASE0_FINAL_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1A_APPLY_INSTRUCTIONS.md](keel-integration/PHASE1A_APPLY_INSTRUCTIONS.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1A_IMPLEMENTATION_REPORT.md](keel-integration/PHASE1A_IMPLEMENTATION_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1A_MIGRATION_AND_COMPATIBILITY.md](keel-integration/PHASE1A_MIGRATION_AND_COMPATIBILITY.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1A_NATIVE_VERIFICATION.md](keel-integration/PHASE1A_NATIVE_VERIFICATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1A_TRACE_MAP.md](keel-integration/PHASE1A_TRACE_MAP.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE1B_BOUNDARY.md](keel-integration/PHASE1B_BOUNDARY.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md](keel-integration/PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE7_DEVELOPER_GUIDE.md](keel-integration/PHASE7_DEVELOPER_GUIDE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE7_REPRODUCIBILITY_REPORT.md](keel-integration/PHASE7_REPRODUCIBILITY_REPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/PHASE7_TEAMMATE_HANDOFF.md](keel-integration/PHASE7_TEAMMATE_HANDOFF.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/README.md](keel-integration/README.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/REMAINING_INTEGRATION_CHECKPOINT.md](keel-integration/REMAINING_INTEGRATION_CHECKPOINT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/ROUTE_MOUNT_MAP.md](keel-integration/ROUTE_MOUNT_MAP.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/SCHEMA_VERIFICATION.md](keel-integration/SCHEMA_VERIFICATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/SOURCE_BASELINES.md](keel-integration/SOURCE_BASELINES.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/SOURCE_BASELINE_VERIFICATION.md](keel-integration/SOURCE_BASELINE_VERIFICATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/SOURCE_SNAPSHOT_RECONCILIATION.md](keel-integration/SOURCE_SNAPSHOT_RECONCILIATION.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/SOURCE_TRACE_CORRECTIONS.md](keel-integration/SOURCE_TRACE_CORRECTIONS.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/TEST_EVIDENCE.md](keel-integration/TEST_EVIDENCE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/TRACE_BOUNDARIES.md](keel-integration/TRACE_BOUNDARIES.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md](keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/architecture/ADR-ACCOUNTING-001-partial-failure-replay-and-crash-charging.md](keel-integration/architecture/ADR-ACCOUNTING-001-partial-failure-replay-and-crash-charging.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-AUTH-001-identity-bootstrap-and-session-policy.md](keel-integration/architecture/ADR-AUTH-001-identity-bootstrap-and-session-policy.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-AUTH-002-platform-authority-and-role-boundaries.md](keel-integration/architecture/ADR-AUTH-002-platform-authority-and-role-boundaries.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-CATALOG-001-catalog-trials-and-existing-contracts.md](keel-integration/architecture/ADR-CATALOG-001-catalog-trials-and-existing-contracts.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-CUSTOM-001-quote-acceptance-versus-activation.md](keel-integration/architecture/ADR-CUSTOM-001-quote-acceptance-versus-activation.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-CUSTOM-002-quote-economics-provider-costs-and-fx.md](keel-integration/architecture/ADR-CUSTOM-002-quote-economics-provider-costs-and-fx.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-ENT-001-feature-rights-units-and-credit-crosswalk.md](keel-integration/architecture/ADR-ENT-001-feature-rights-units-and-credit-crosswalk.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-IMPORT-001-canonical-identity-stock-and-invoice-ownership.md](keel-integration/architecture/ADR-IMPORT-001-canonical-identity-stock-and-invoice-ownership.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-MPI-001-mpi-eligibility-sample-and-public-reliability.md](keel-integration/architecture/ADR-MPI-001-mpi-eligibility-sample-and-public-reliability.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-PRICE-001-pricing-evidence-freshness-and-fallback.md](keel-integration/architecture/ADR-PRICE-001-pricing-evidence-freshness-and-fallback.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-PRIVACY-001-provider-privacy-and-retained-business-records.md](keel-integration/architecture/ADR-PRIVACY-001-provider-privacy-and-retained-business-records.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-PROMO-001-promotion-authority-redemption-and-stacking.md](keel-integration/architecture/ADR-PROMO-001-promotion-authority-redemption-and-stacking.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/ADR-TRANSITION-001-effective-grants-and-mixed-plan-change.md](keel-integration/architecture/ADR-TRANSITION-001-effective-grants-and-mixed-plan-change.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-auth.md](keel-integration/architecture/FEATURE-auth.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-billing.md](keel-integration/architecture/FEATURE-billing.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-entitlements.md](keel-integration/architecture/FEATURE-entitlements.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-imports.md](keel-integration/architecture/FEATURE-imports.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-mpi.md](keel-integration/architecture/FEATURE-mpi.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-pricing.md](keel-integration/architecture/FEATURE-pricing.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/architecture/FEATURE-stores.md](keel-integration/architecture/FEATURE-stores.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/keel-integration/evidence/README.md](keel-integration/evidence/README.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/evidence/phase0r/EVIDENCE_GUIDE.md](keel-integration/evidence/phase0r/EVIDENCE_GUIDE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/reference/EXECUTION_CONTRACT.md](keel-integration/reference/EXECUTION_CONTRACT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md](keel-integration/reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/reference/KEEL_PHASE0V_WORK_PROMPT_20261020.md](keel-integration/reference/KEEL_PHASE0V_WORK_PROMPT_20261020.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/reference/LEDGER_TEMPLATE.md](keel-integration/reference/LEDGER_TEMPLATE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/reference/PHASE0_INDEPENDENT_REVIEW_AND_NEXT_PROMPT.md](keel-integration/reference/PHASE0_INDEPENDENT_REVIEW_AND_NEXT_PROMPT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-AUTH.md](keel-integration/traces/TRACE-AUTH.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-CONNECT.md](keel-integration/traces/TRACE-CONNECT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-CREDIT.md](keel-integration/traces/TRACE-CREDIT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-CUSTOM.md](keel-integration/traces/TRACE-CUSTOM.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-ENT.md](keel-integration/traces/TRACE-ENT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-IMPORT.md](keel-integration/traces/TRACE-IMPORT.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-MPI.md](keel-integration/traces/TRACE-MPI.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-PLATFORM.md](keel-integration/traces/TRACE-PLATFORM.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-PRICE.md](keel-integration/traces/TRACE-PRICE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-PROMO.md](keel-integration/traces/TRACE-PROMO.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-SHOP.md](keel-integration/traces/TRACE-SHOP.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-STORE.md](keel-integration/traces/TRACE-STORE.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-SUB.md](keel-integration/traces/TRACE-SUB.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/keel-integration/traces/TRACE-WOO.md](keel-integration/traces/TRACE-WOO.md) | History | Retain dated evidence; not ordinary onboarding instructions |
| [docs/perf/README.md](perf/README.md) | Reference | Retain technical/operator or approved-decision reference |
| [docs/reference/ENVIRONMENT_INVENTORY.md](reference/ENVIRONMENT_INVENTORY.md) | Reference | Useful generated source index; regenerated and checked |
| [frontend/README.md](../frontend/README.md) | Primary | Current developer guide; improved or retained |
| [tools/keel-verification/README.md](../tools/keel-verification/README.md) | Reference | Retain technical/operator or approved-decision reference |

</details>
