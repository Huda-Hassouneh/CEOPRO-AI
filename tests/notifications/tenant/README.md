# Tenant Notification Tests

Protects tenant-facing notifications, currently including the custom-plan-offer workflow.

| File | What it tests |
| --- | --- |
| `tenant-notification-definition.test.ts` | `CUSTOM_PLAN_OFFER_READY` maps to an INFO billing notification with the correct resource/dedupe/recipient policy; malformed/unsupported events fail closed. |
| `tenant-notification-migration-contract.test.ts` | Composite tenant membership, FORCE RLS, narrow worker permissions, and separation between application producer identity and worker identity. |
| `tenant-notification-producer.test.ts` | Idempotent tenant-scoped outbox event creation with correct payload and rejection of empty quote IDs. |
| `tenant-notification-source-contract.test.ts` | Quote-send + notification atomic transaction, tenant notification routes/mount path, dedicated worker Prisma usage, `manage_billing` recipient selection, and custom-plan acceptance permission boundary. |

These tests are intended to catch authorization, RLS, transactional-outbox, and worker-isolation regressions early.
