# KEEL

KEEL helps businesses turn sales, products, stock and market evidence into practical decisions: analytics, demand forecasts, price recommendations, competitor monitoring, sentiment, campaign assets, document-grounded assistance and alerts.

The unified app has one Python/FastAPI business authority. React/Vite is the customer and operator UI. PostgreSQL stores canonical tenant data and enforces row-level security. Redis supports streams, cache and rate limits; MinIO/S3-compatible storage holds uploads and assets. Python remains the authority for Stripe, subscriptions, entitlements, Credits, usage and workers.

## Start here

- Contributor setup and verification: [docs/keel-integration/PHASE7_DEVELOPER_GUIDE.md](docs/keel-integration/PHASE7_DEVELOPER_GUIDE.md)
- Feature inventory and practical tests: [docs/keel-integration/FEATURE_INVENTORY.md](docs/keel-integration/FEATURE_INVENTORY.md)
- Teammate/reviewer handoff: [docs/keel-integration/PHASE7_TEAMMATE_HANDOFF.md](docs/keel-integration/PHASE7_TEAMMATE_HANDOFF.md)
- Phase 6 integrated acceptance: [docs/keel-integration/PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md](docs/keel-integration/PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md)
- Phase 7 reproducibility and browser evidence: [docs/keel-integration/PHASE7_REPRODUCIBILITY_REPORT.md](docs/keel-integration/PHASE7_REPRODUCIBILITY_REPORT.md)
- Unified implementation ledger: [docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md](docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md)
- Backend settings: [backend/.env.example](backend/.env.example)
- Frontend settings: [frontend/.env.example](frontend/.env.example)

## Quick start

For full Windows development, use WSL 2:
~~~~bash
./keel setup       # once per checkout
./keel start       # services, migrations, FastAPI and Vite
./keel workers     # separate terminal for market workers
./keel seed        # optional synthetic companies; prompts for local password
~~~~

For focused acceptance work, reuse tools/keel-verification/README.md instead of creating a venv or Docker stack. Its reset affects only the dedicated keel_verification database.

## Verification status

Phase 6 passed the exercised local matrix with controlled fixtures. Live provider certification and owner-controlled commercial/security decisions remain open. Fixtures are not production certification or deployment approval; read the linked evidence.
