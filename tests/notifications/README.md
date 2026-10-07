# Notification Tests

Notification tests are grouped by recipient boundary because platform-admin notifications and tenant notifications have different events, permissions, routes, RLS rules, and worker access contracts.

- `platform/` — platform/admin-facing notification pipeline.
- `tenant/` — tenant-user notification pipeline.

Both subfolders validate the same four architectural layers: definition/payload mapping, migration/RLS security, producer/outbox behavior, and source-level transaction/route/worker contracts.
