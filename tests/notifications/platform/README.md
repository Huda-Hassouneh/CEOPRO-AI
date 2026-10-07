# Platform Notification Tests

Protects the platform-admin notification pipeline, currently centered on billing/payment failures.

| File | What it tests |
| --- | --- |
| `platform-notification-definition.test.ts` | `PAYMENT_FAILED` maps to a CRITICAL billing notification, allows nullable paymentIntentId, rejects malformed payloads, and fails closed for unsupported events. |
| `platform-notification-migration-contract.test.ts` | Tenant-scoped dedupe, FORCE RLS, and a dedicated notification worker role that is non-superuser/non-BYPASSRLS with narrow grants. |
| `platform-notification-producer.test.ts` | Idempotent tenant-scoped outbox creation and rejection of empty Stripe event IDs used in dedupe keys. |
| `platform-notification-source-contract.test.ts` | Stripe event ID propagation, payment persistence + outbox atomic transaction, recipient-scoped HTTP operations, dedicated worker Prisma client usage, and worker DB URL isolation. |

These are deterministic unit/source/migration contract tests; they do not require a live Stripe webhook delivery.
