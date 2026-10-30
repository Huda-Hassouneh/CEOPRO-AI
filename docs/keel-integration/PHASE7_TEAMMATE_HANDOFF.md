# Phase 7 teammate and review handoff

## Integration scope

This branch brings approved KEEL workflows under one Python authority while preserving advanced teammate Python capabilities. Phase 6 records the merged upstream snapshot as 041f9f24a6a32d8d03d934a3f89b6b3734eecadb. Read the unified ledger and Phase 6 report for acceptance IDs and code provenance.

Runtime: React/Vite → FastAPI → PostgreSQL canonical records with restricted-role RLS; Redis supplies streams/cache/rate limits; MinIO stores files and assets. Python remains the sole authority for Stripe, subscriptions, entitlements, usage and Credits. External records remain staging/evidence until approved promotion rules apply. Node reference is read-only.

## Verification handoff

Phase 6 local acceptance passed for the exercised matrix: 780 focused backend tests passed, one live Stripe case skipped, 137 frontend tests passed, lint/build and /health/ready passed, and fresh 1–103 plus populated 1–102→103 upgrade/rerun passed. Its report separates fixture evidence from live providers and lists every not-run case.

Phase 7 added:
- Authenticated platform Owner/Admin lifecycle and directory Chromium flow: 26 assertions, zero failed/skipped, synthetic identities, local SMTP and dedicated keel_billing_test_* PostgreSQL database.
- Shopify/Woo input validation and Marketing capability/RTL smoke: 9 assertions in 3 scenarios passed on current FastAPI/Vite. No OAuth, store API, LLM or image provider call.
- Current-source competitor browser smoke passed English desktop and Arabic 390px RTL; this was a supporting check, not a replacement for Phase 6 broader evidence.
- Migration inventory remains 103. No production business logic or schema changed.

Full Marketing image gallery generation and actual Shopify/Woo authorize/connect/sync browser flows remain unverified. The form smoke does not certify a merchant connection. These require approved test merchant/OAuth and/or model/image provider setup. No provider credentials were configured, so no external provider calls were made.

## Fresh-clone and environment findings

backend/.env.example and frontend/.env.example are tracked config templates. Optional variables and worker/provider contracts are traced in the setup guide and source docs. Phase 6 installed parser/runtime packages in the existing venv. Phase 7 identified that auth_browser_verification.py imports aiosmtpd while Install-Python.ps1 omitted it; the installer now declares it.

The reusable environment was reused. A clean tracked-source archive validates links and referenced files; no second full Python environment, Node install or Docker stack was created. A full fresh-clone dependency installation was not repeated because it would duplicate the existing reusable stack. Full local setup uses WSL Bash.

## Migrations and rollout

Migrations 1–103 are the accepted history. Migration 103 provides durable tenant notifications and passed Phase 6 fresh/populated upgrade tests. Do not edit or renumber them; Migration 104+ is unauthorized. Apply via the Compose one-shot migrate service or backend/scripts/apply_migrations.py using the schema-owner URL and APP_DB_PASSWORD. Runtime traffic must use ceopro_app.

Production rollout was not certified. Follow the deployment owner's backup/migration runbook. There is no reverse migration chain; the generic recovery route is restore from a verified pre-upgrade backup plus app version after assessing writes. Do not improvise a production SQL rollback.

## Remaining release gates

- AUTH-004 issuer/audience and AUTH-013 legacy Node identity cutover.
- U1–U5/U7 and O-PRICE/O-MPI plus catalog/provider/canonical posting approvals in the decision register. Do not invent aliases, grants, charging, FX, refunds or stock rules.
- Live Stripe, Shopify, WooCommerce, discovery/scraping, LLM/embedding and image-provider certification.
- Exceptional platform finance/catalog permissions and platform notification delivery remain partial/gated.
- Marketing gallery browser flow, dedicated competitor image gallery, MPI history persistence and notification account-erasure policy remain as recorded in Phase 6.
- Promotions/custom-offer acceptance was not executed in Phase 6.
- Do not activate new grants for system_alerts, ai_pricing, dashboard_analytics, market_perception, business_recommendations, product_management or inventory_intelligence without approval.

This handoff is not production deployment approval.

## Reviewer checklist

1. Confirm branch ancestry and final team-main synchronization. Local origin/main still points at the merged snapshot; Phase 7 did not fetch or merge.
2. Review migration count and confirm no 1–103 file changed.
3. Distinguish current versus inherited test evidence, fixtures, blocked providers and unrun workflows.
4. Check .env and browser fixture files are ignored/outside Git; run secret scanning before a later PR.
5. Re-run the Platform browser and Test-HandoffBrowser.ps1 plus relevant focused backend/frontend checks.
6. Verify schema-owner/app-role split, JWT/vault secrets, CORS/origins, storage, Stripe test/live separation and worker actor identities.
7. Resolve owner decisions and provider certification before release.
8. Obtain normal review and deployment authorization in a later task. Phase 7 created no PR or deployment.