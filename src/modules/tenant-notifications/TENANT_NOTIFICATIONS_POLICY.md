# CEOPRO Tenant Notifications Policy

## Scope

Tenant notifications are customer-facing notifications for a single customer tenant. They are intentionally separate from `platform_*` notifications, which belong to the CEOPRO Platform Admin inbox.

## Delivery pattern

```text
business action
  -> tenant_notification_outbox
  -> tenant notification worker
  -> tenant_notifications
  -> tenant_notification_receipts
  -> /notifications API
  -> customer dashboard bell/inbox
```

The normal application process only produces outbox work. The dedicated `ceopro_notification_worker` database identity performs cross-tenant dispatch work using narrow grants and FORCE RLS policies.

## First event

### CUSTOM_PLAN_OFFER_READY

Produced when a Platform Admin sends an approved custom-plan quote to a customer tenant.

Recipient policy:

- active tenant owner (`permissions.all = true`), or
- any active tenant member whose role has `manage_billing = true`.

The notification references the quote as:

```text
resourceType = custom_plan_quote
resourceId   = quote id
```

The frontend should route the recipient to the existing custom-plan offer page using the resource identifier. The backend does not hardcode a frontend URL.

## API

Authenticated active tenant members use:

```text
GET  /notifications
GET  /notifications/unread-count
POST /notifications/read-all
POST /notifications/:id/read
POST /notifications/:id/archive
```

A user can only see or update their own receipt. Having access to the route does not grant access to notifications for which no receipt exists.

## Isolation rules

- `tenant_notifications.tenant_id` identifies the customer tenant.
- Receipt membership is enforced by the composite foreign key `(tenant_id, recipient_user_id) -> tenant_users(tenant_id, user_id)`.
- All three tenant notification tables use FORCE RLS.
- The web role cannot directly create final notifications or receipts.
- The worker cannot delete notifications, receipts, or outbox rows.
- Platform Admin and tenant notification tables remain separate.

## Producer rule

`CUSTOM_PLAN_OFFER_READY` is produced in the same database transaction that changes the custom-plan quote from `approved` to `sent`. This prevents a sent quote from existing without its durable notification outbox event.

The Platform Admin producer stays on the normal `ceopro_app` connection. It never uses `notificationWorkerPrisma`. A dedicated RLS policy authorizes this cross-tenant outbox INSERT only for an active Platform Admin actor with `billing.manage` or `all` permission.

## Worker rule

The tenant worker reuses `NOTIFICATION_WORKER_DATABASE_URL` and the existing `ceopro_notification_worker` role. It has only the additional grants required to:

- SELECT/UPDATE tenant notification outbox work;
- SELECT/INSERT tenant final notifications;
- INSERT tenant receipts;
- read the minimum tenant membership/role data needed for recipient resolution.

Retry behavior mirrors the Platform Admin notification worker: bounded batches, claim lease, exponential backoff, and permanent failure after five claims.
