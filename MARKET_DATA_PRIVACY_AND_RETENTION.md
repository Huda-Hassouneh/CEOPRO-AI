# CEOPRO AI Market Data Privacy and Retention Policy

## Scope

This policy covers public market pages, product observations, prices, reviews, reviewer names,
source responses, staging rows, events, and derived scores collected by the Market Scraper Service.
It implements the Technical Specification's Tier 2 quarantine, Tier 4 traceability, Tier 5 external-
content safety, and Tier 7 evidence requirements.

## Collection principles

1. Collect only data needed for an enabled tenant capability.
2. A source remains `RESTRICTED` until an accountable reviewer records an approval reference.
3. Prefer official APIs, then feeds, then structured page data, and use HTML scraping only as a
   reviewed fallback.
4. Collect only public, approved URLs. Never bypass authentication, CAPTCHAs, paywalls, robots
   controls, or technical access restrictions.
5. Do not collect special-category personal data. Reviewer names are optional personal data and
   must be marked during source review.
6. Every record retains tenant, source, job, mapping, and collection-time lineage.

## Tier 2 staging decision

Market collection uses `market_observation_staging`, a specialized Tier 2 quarantine table, rather
than the generic `import_staging_rows`. Market candidates need product-mapping IDs, content hashes,
safety flags, and the statuses `REJECTED`, `QUARANTINED`, and `PROMOTED`, which the generic business-
file staging contract cannot represent without weakening its existing constraints.

The flow is:

```text
raw candidate -> PENDING -> REJECTED | QUARANTINED | PROMOTED
```

Only `PROMOTED` product candidates may create canonical `competitor_prices`, `market_observations`,
events, or alerts. Product/page-text quarantine blocks price promotion. Reviews are isolated child
records: a flagged review is stored as `QUARANTINED` and excluded from sentiment/LLM consumers, but
does not invalidate a separately verified safe product price.

## Retention

Each source has a reviewed `retention_days` value (default 90, allowed range 1–3650). The maintenance
worker periodically:

- deletes expired raw market staging rows;
- removes expired page text and raw payloads from canonical observations while retaining minimal
  numerical/provenance history;
- anonymizes expired reviewer names.

Canonical prices, event timestamps, aggregate scores, and non-personal provenance may be retained
for trend analysis according to the tenant's contractual retention policy. Deletion requests or
legal holds override automatic retention and must be handled by the platform privacy owner.

## Access and tenant isolation

PostgreSQL Row-Level Security is mandatory. Runtime services use the restricted `ceopro_app` role,
set `app.current_tenant_id` and `app.current_user_id`, and never use migration-superuser credentials.
Raw and quarantined content must not be exposed to normal dashboard or LLM consumers.

## Operational review checklist

Before setting a source to `ALLOWED`, record:

- accountable reviewer UUID;
- approval/ticket/reference URL;
- terms and robots review result;
- privacy review timestamp;
- whether personal data may be present;
- retention period;
- collection method and rate limit;
- selectors/API contract and test fixture;
- rollback owner and monitoring contact.

Technical checks do not replace legal authorization. Approval must be renewed when source terms,
robots rules, collection behavior, or requested data materially change.

## Incident response

Disable the source (`is_active = FALSE` or policy `BLOCKED`) when collection is unauthorized,
unsafe, unexpectedly captures personal data, repeatedly fails, or causes source complaints. Preserve
audit logs, stop downstream processing, notify the privacy/security owner, and apply deletion or
legal-hold instructions before re-enabling collection.
