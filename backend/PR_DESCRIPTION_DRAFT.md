## Summary
- Competitor comments: YouTube collection ranked by place, daily search cap, stale-comment refresh, filter tuned on 502 real comments, review index.
- Price comparison tiers: stricter spec matching, accuracy gate, added-value guidance, category and owner-set premium bands, report screen with CSV, ladder in assistant and reports.
- Menu OCR: real-tesseract tests; CI now installs tesseract (Arabic + English) so they run.
- `/billing` routes fail closed when Redis is down (signed-out tokens are refused); other routes still fail open.
- Tooling: secret scanning, live-DB suite runner, MinIO in the CI backend job.

## Deploy
Apply the 16 migrations in `backend/MIGRATIONS_TO_APPLY.md` with or before the code. Then refresh comparisons once per company.

## Testing
- Full backend suite in a CI-matching environment: 3,417 passed, 43 skipped, 0 failed (#122). Frontend: 83/83.
- `test_menu_media_real_ocr.py`: 3 passed on tesseract 5.5.0 (synthetic pictures; real photos still need staging, #86).
- Auth tests: 46 passed after the fail-closed change.

## Still open
See `backend/PENDING_ACTIONS.md` (keys, legal approvals, Arabic review, live runs).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
