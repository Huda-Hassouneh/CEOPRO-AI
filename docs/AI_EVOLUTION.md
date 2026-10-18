# AI source provenance in this review release

This document supersedes the previous custom competitor change history. See [COMPETITOR_REVIEW.md](COMPETITOR_REVIEW.md) for behavior, deployment and boundaries.

- Base: Python `backend/` from the supplied `latest-teammate keel_test.zip`, installed as `ai/`.
- Restored without edits: complete `src/market_scraper/` subtree and `src/ai/pricing/competitor_classification.py` (170 files, exact hashes in `TEAM_COMPETITOR_HASHES.json`).
- Retained integration overlays: Node-authenticated store adapters, Node-facing business insights, canonical sales/evidence gates, scoped MinIO credentials and tenant-specific generated summary keys. Exact differences are in `AI_REVIEW_OVERLAYS.csv`.
- Removed custom competitor additions include the extra discovery scope/control/job modules, identity/offer/probe/category helpers and verification script. Some similarly named capabilities now exist in the team's source; their presence does not imply retention of our implementation. Compare file hashes rather than names alone.
- Current team dependencies, migrations and standalone API remain source references. No standalone Python migration has been applied to the integrated PostgreSQL database, and no new subscription ownership has been moved out of Node.

The older input archives remain the source for historical versions. This review package is not a reconstruction of every milestone or a full Git history. Offline checks and isolated integration tests do not establish that every team AI endpoint works with Node's database schema. The custom competitor bridge is deliberately suspended until a contract review/reintegration is completed.
