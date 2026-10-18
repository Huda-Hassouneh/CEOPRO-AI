# Security and publication

Report vulnerabilities privately to the repository maintainers through your team's established channel or GitHub private vulnerability reporting if enabled. No public security email is supplied by this repository. Do not post credentials, exploit payloads with real tenant data, document contents or full production connection strings in issues.

## Required boundaries

- Keep Node as the authority for identity, permission, subscriptions and canonical writes. Retain PostgreSQL RLS/FORCE RLS and fixed-search-path, restricted-grant policy helpers. Runtime roles must never be superuser or BYPASSRLS.
- Keep administrator/bootstrap credentials out of runtime services. The DEV helper refuses production; it is not a production provisioning policy.
- Store provider secrets server-side; VITE settings are public. Retain AES-GCM encryption keys securely and plan credential re-encryption before rotation. Back up encrypted data and keys separately.
- Verify raw Stripe/Shopify webhook signatures before parsing business payloads, deduplicate events and treat browser return URLs as untrusted status signals.
- Preserve SSRF/public-DNS/redirect/robots controls. Authorization evidence must reflect genuine terms or written permission; do not claim consent with a sample placeholder. No CAPTCHA/login bypass is supplied.
- Respect tenant storage quotas, file/extraction bounds and supported refund/price provenance. Review numeric observations and source retention instead of retaining unnecessary raw pages/customer text indefinitely.
- Source retention maintenance defaults to 90 days where configured (bounded 1–3650); it prunes eligible raw data while preserving numeric provenance. Run maintenance only under its intended authorized actor and backup policy. Quarantined review material must not be silently treated as usable evidence.

## Before publishing

This cleaned source copy excludes actual root/frontend/AI env files, local dependency trees and build output. A hardcoded password in the legacy bootstrap-role SQL was replaced by a required psql variable. Treat all secrets that appeared in an earlier shared archive as potentially exposed and rotate them through the relevant providers/database operator; cleanup cannot revoke old copies or erase Git history.

Review your own Git history and secret-manager references before pushing. Gitignore prevents new accidental adds, not already tracked files. Never use `git add -f` on local env files. Do not publish database dumps, customer exports, browser traces/storage state, private signing keys or tunnel tokens. Store test accounts must be fictional and test-mode payment configuration must be distinguishable from live configuration.

The legacy Python token-rotation tool is not a verified Node JWT rotation workflow. Production must independently provide TLS, stable domains, managed secrets, backups/restore testing, worker supervision, dependency review and monitoring. Backend package metadata says ISC; no repository-wide LICENSE file was supplied. Maintainers must decide licensing before representing the whole repository as open source.
