# KEEL isolated review handoff — 18 October 2026

This package supersedes the earlier handoff for competitor integration behavior.

- Inputs: supplied `keel(4).zip` and `latest-teammate keel_test.zip`.
- Active layout: `backend/` Node, `frontend/` integrated React, `ai/` current team Python plus retained integration overlays.
- Custom competitor Python subtree replaced with the supplied team's source, verified byte-for-byte.
- Dependent custom Node work producers, subprocess checkers and dispatcher suspended; matching/collection controls and Smart Alerts hidden.
- Existing database history retained; one new migration disables the sales-import discovery trigger. No live database or GitHub mutation performed.
- Store connectors, canonical sales, business insights, RAG, forecasting and independent pricing UI/source retained. Current team Python changes outside the competitor subtree are present; this package does not claim complete live validation of all their endpoints.

Start with [COMPETITOR_REVIEW.md](COMPETITOR_REVIEW.md). Actual commands and limits are in [REVIEW_VERIFICATION.md](REVIEW_VERIFICATION.md). Exact package differences from the supplied integrated archive are in [REVIEW_CHANGED_FILES.csv](REVIEW_CHANGED_FILES.csv); Python overlays relative to the supplied team snapshot are in [AI_REVIEW_OVERLAYS.csv](AI_REVIEW_OVERLAYS.csv).

The original documentation-consolidation report described a previous package. Current team notes have been restored, so its old count of 18 Markdown files no longer applies. The current handoff validator checks active integrated documentation links and environment definitions; imported team documentation is retained as reference, with original path assumptions.

No claim is made that all historical tests pass. Tests for the withdrawn custom competitor protocol are retained as historical source and are outside this release's acceptance gate. Use `npm run test:competitor-boundary` for the intentional suspension behavior. No screenshot or browser-based responsive/accessibility verification was performed in this task.
