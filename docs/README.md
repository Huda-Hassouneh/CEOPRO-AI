# KEEL documentation

## Current contributor guidance

- [Local development and command reference](LOCAL_DEVELOPMENT.md)
- [Architecture and request/data flows](ARCHITECTURE.md)
- [Database, migrations, roles and fixtures](DATABASE.md)
- [Environment variables](ENVIRONMENT_VARIABLES.md)
- [Workers and background tasks](WORKERS.md)
- [External integrations](INTEGRATIONS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)
- [Developer tooling verification](DEVELOPER_EXPERIENCE_VERIFICATION.md)
- [PR CI remediation and verification checkpoint](CI_REPAIR.md)
- [Recover development and isolated test environments after reboot](TEST_ENVIRONMENT_RECOVERY.md)
- Component guides: [backend](../backend/README.md), [frontend](../frontend/README.md)

These are the root development-command instructions. Older Phase 7 and RUNNING_LOCALLY guides describe the earlier WSL/verification harness. The harness remains useful for specialist acceptance tests; it is not a fresh-clone requirement.

## Current architecture and domain references

- [Data ownership/contracts](../backend/src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md)
- [Subscriptions and Credits](SUBSCRIPTIONS_AND_CREDITS.md)
- [Provider keys/accounts](../backend/KEYS_AND_ACCOUNTS_NEEDED.md)
- [Scraper/collection architecture](../backend/src/market_scraper/README.md)
- [Integration feature inventory](keel-integration/FEATURE_INVENTORY.md)
- [Final differential acceptance](keel-integration/PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md)
- [Remaining integration checkpoint](keel-integration/REMAINING_INTEGRATION_CHECKPOINT.md)

## Historical decisions and evidence

`keel-integration/`, `archive/`, `remediation/`, backend reports and the unified file-change ledger retain implementation decisions, owner approvals and acceptance evidence. They are not competing startup guides. Earlier test counts, branch revisions and migration totals describe their recorded runs.

`CODESPACES_DEVELOPMENT.md` remains the Codespaces-specific workflow. `STAGING_DEPLOYMENT.md` and billing runbooks describe deployment/operator activities, not authorization to deploy from a development setup.

No architecture decisions, migration records or acceptance reports were deleted for this documentation cleanup. Generated local logs and test XML stay in ignored `.dev/`.
