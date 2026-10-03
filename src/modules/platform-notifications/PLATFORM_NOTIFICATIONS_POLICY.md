# CEOPRO Platform Notification Recipient Policy

## 1. Purpose

This policy defines **who is allowed to receive Platform Administration notifications in CEOPRO**.

It applies to notifications stored in:

- `platform_notifications`
- `platform_notification_receipts`

and produced through:

- `platform_notification_outbox`
- the Platform Notification Dispatcher / Worker

This policy applies only to the **CEOPRO Platform Admin inbox**.

It does **not** define tenant/customer-facing notifications.

---

## 2. Core Rule

Platform notification recipients must be determined by **verified platform membership and permissions**, not merely by a role name.

A user must never receive a Platform Admin notification simply because they:

- belong to the source/customer tenant;
- have the role `owner` in a customer tenant;
- have the role `admin` in a customer tenant;
- can access some unrelated CEOPRO feature.

The source tenant identifies **where the event happened**.

It does not identify **who receives the Platform Admin notification**.

Example:

```text
Acme customer tenant
        ↓
PAYMENT_FAILED
        ↓
source_tenant_id = Acme
        ↓
Platform Notification Dispatcher
        ↓
eligible users of the CEOPRO platform tenant
```

---

# 3. Audience Boundary

`platform_notifications` is a **Platform Administration inbox**.

Therefore eligible recipients must belong to the canonical CEOPRO platform tenant.

The dispatcher must never generate `platform_notification_receipts` for ordinary customer-tenant users.

This includes customer:

- owners;
- admins;
- managers;
- accountants;
- staff;
- other tenant users.

If CEOPRO later introduces customer-facing notifications, they must use a separate tenant-facing notification policy and delivery path.

The same business event may eventually generate both:

```text
PAYMENT_FAILED
      │
      ├── Platform notification
      │      → CEOPRO platform staff
      │
      └── Tenant notification
             → affected customer's users
```

Those audiences must remain separate.

---

# 4. Platform Membership Requirement

Before considering notification permissions, a recipient must have an **active and verified membership in the canonical CEOPRO platform tenant**.

The recipient check must follow the same platform-access boundary already used by the Platform Admin portal.

Conceptually:

```text
User
 ↓
active authenticated user?
 ↓
member of canonical platform tenant?
 ↓
membership active/verified?
 ↓
authorized platform role?
 ↓
notification permission?
 ↓
event-domain permission?
 ↓
eligible recipient
```

A customer owner with:

```text
roleKey = "owner"
```

must **not** pass this check unless that membership belongs to the canonical CEOPRO platform tenant.

Role names alone are therefore insufficient.

---

# 5. Supported Platform Roles

The currently authorized Platform Administration roles are:

```text
owner
admin
```

Other system roles such as:

```text
manager
accountant
staff
```

must not automatically receive Platform Admin notifications.

If CEOPRO introduces another platform role later, that role must be explicitly added to the Platform Administration authorization model before it becomes eligible for notifications.

---

# 6. Platform Owner Policy

The verified Platform Owner has full platform access.

The owner therefore receives all Platform Admin notifications by default.

Conceptually:

```text
platform owner
    ↓
{ all: true }
    ↓
eligible for every platform notification
```

This prevents critical alerts from becoming invisible because of an incomplete event-to-permission mapping.

The owner must still satisfy:

- authenticated user requirements;
- canonical platform tenant membership;
- active/verified membership requirements.

A customer-tenant owner is not covered by this rule.

---

# 7. Platform Admin Policy

Platform admins must **not automatically receive every notification**.

A Platform Admin receives an event only when:

1. the user has valid Platform Administration access;
2. the user is permitted to read Platform notifications;
3. the user has the permission associated with the event's business domain.

Conceptually:

```text
Platform Admin
      ↓
notifications.read
      +
domain permission
      ↓
receipt created
```

Example:

```text
PAYMENT_FAILED
      ↓
requires billing.read

Admin A
billing.read ✅
→ receives notification

Admin B
users.read ✅
billing.read ❌
→ does not receive notification
```

This avoids exposing irrelevant or sensitive operational information to admins who do not work with that area.

---

# 8. Inbox Permissions vs Domain Permissions

Two types of permissions must remain separate.

## Inbox permission

Controls whether an admin can use the notification system itself.

Examples:

```text
notifications.read
notifications.manage
```

`notifications.read` controls access to the Platform Admin inbox.

`notifications.manage` may be used for administrative notification-management capabilities if CEOPRO introduces them.

Normal personal receipt operations such as:

```text
mark my notification read
archive my notification
```

must remain limited to the authenticated user's own receipt.

## Domain permission

Controls whether the user is authorized to know about the underlying business event.

Examples already present in the CEOPRO Platform Admin authorization model include:

```text
platform.overview.read

companies.read
companies.update
companies.status.manage

users.read
users.manage

adminTeam.read
adminTeam.invite
adminTeam.roles.manage
adminTeam.remove

auditLogs.read

platformSettings.read
platformSettings.manage

billing.read
billing.manage
billing.pricing.manage

subscriptions.read
```

A user having `notifications.read` does **not** mean they should receive every event.

Example:

```text
notifications.read ✅
users.read ✅
billing.read ❌

PAYMENT_FAILED
→ do not create receipt
```

---

# 9. Event-to-Permission Mapping

Every Platform Admin notification event must declare its recipient permission policy explicitly.

The mapping should live centrally in the Platform Notification module.

It must not be distributed across:

- Stripe handlers;
- forecasting handlers;
- ingestion handlers;
- controllers;
- frontend components.

Example policy:

| Event                              | Required domain permission |
| ---------------------------------- | -------------------------- |
| `PAYMENT_FAILED`                   | `billing.read`             |
| `PAYMENT_ACTION_REQUIRED`          | `billing.read`             |
| `INVOICE_FINALIZATION_FAILED`      | `billing.read`             |
| `SUBSCRIPTION_CANCELLED`           | `subscriptions.read`       |
| `TRIAL_ENDING`                     | `subscriptions.read`       |
| Company registration/status events | `companies.read`           |
| Platform user events               | `users.read`               |
| Platform Admin Team events         | `adminTeam.read`           |
| Security/audit events              | `auditLogs.read`           |
| Platform configuration events      | `platformSettings.read`    |
| Pricing/vendor-rate events         | `billing.pricing.manage`   |

Permissions for operational domains that do not currently have an established Platform Admin permission must **not be invented inside the notification system**.

For example, if CEOPRO adds:

```text
FORECAST_FAILED
INGESTION_FAILED
AI_SERVICE_UNAVAILABLE
DATA_SOURCE_SYNC_FAILED
```

and no corresponding Platform Admin permission currently exists, the notification policy must not silently invent:

```text
forecasting.read
ingestion.read
ai.read
```

Instead, such events must initially fall back to the Platform Owner until the Platform Administration permission model explicitly introduces the required permission.

---

# 10. Fail-Closed Recipient Policy

Unknown or incorrectly configured notification events must never be broadcast to all admins.

If an event has no recognized recipient policy:

```text
UNKNOWN_EVENT
      ↓
no domain permission mapping
```

the dispatcher must:

1. deliver it to eligible Platform Owner recipients only;
2. not broadcast it to all Platform Admins;
3. log/record that the notification policy mapping is missing;
4. require an explicit mapping before normal admin delivery is enabled.

Conceptually:

```ts
if (!policy) {
  return platformOwnersOnly;
}
```

Never:

```ts
if (!policy) {
  return everyPlatformUser;
}
```

This is the safer default.

---

# 11. Recommended Event Definition Contract

The recipient rules should be part of the central notification definition.

Example:

```ts
{
  eventType: "PAYMENT_FAILED",

  severity: "CRITICAL",

  titleKey:
    "platformNotifications.paymentFailed.title",

  bodyKey:
    "platformNotifications.paymentFailed.body",

  resourceType: "subscription",

  recipientPolicy: {
    audience: "platform_admin",

    requiredPermissions: [
      "billing.read"
    ],

    permissionMode: "ANY",

    ownerAlwaysReceives: true
  }
}
```

The Stripe handler must not decide recipients.

The Stripe handler only produces:

```text
PAYMENT_FAILED
```

The notification subsystem decides:

```text
severity
title/body
resource
recipient permissions
```

---

# 12. Recipient Resolution

The dispatcher should conceptually perform:

```ts
async function getNotificationRecipients(
  platformTenantId: string,
  policy: RecipientPolicy
): Promise<string[]> {
  // 1. Load active/verified platform memberships.
  // 2. Restrict to authorized platform roles.
  // 3. Include qualified platform owner(s).
  // 4. For admins:
  //      require notifications.read
  //      require event-domain permission.
  // 5. Return unique user IDs.
}
```

The implementation must reuse the existing Platform Administration membership and permission repositories.

It must not create a second independent definition of:

```text
Who is a platform admin?
Who is an owner?
What permissions does this user have?
```

The same authorization source used by Platform Admin routes must remain the source of truth.

---

# 13. Receipt Creation

Once recipient user IDs have been resolved, the dispatcher creates one receipt per recipient:

```text
platform_notification_receipts

notification_id
platform_tenant_id
recipient_user_id
read_at
archived_at
```

Example:

```text
PAYMENT_FAILED notification

Owner
→ receipt ✅

Billing Admin
billing.read ✅
→ receipt ✅

User Admin
users.read ✅
billing.read ❌
→ no receipt

Customer Owner
not platform member
→ no receipt
```

The unique receipt constraint must guarantee that the same notification cannot create multiple receipts for the same user.

---

# 14. Permission Changes After Delivery

Recipient eligibility is evaluated **when the dispatcher creates the notification receipts**.

If a user's permission is later removed, normal Platform Administration authorization must still be checked when the user attempts to access the inbox.

Possession of an existing receipt must never bypass current authorization.

Therefore:

```text
receipt exists
```

does not mean:

```text
authorization automatically exists forever
```

Platform Admin API endpoints must continue validating current platform access.

---

# 15. Read and Archive State

Notification delivery and notification acknowledgement are separate concerns.

A recipient may modify only their own:

```text
read_at
archived_at
```

A Platform Admin must never mark another Platform Admin's personal receipt as read or archived through the normal inbox API.

Example:

```text
Admin A
→ may update Admin A receipt

Admin A
→ may NOT update Admin B receipt
```

The existing RLS policy must remain the final database-level protection.

---

# 16. Notification Visibility Does Not Grant Resource Access

Receiving a notification must never automatically grant access to the resource referenced by that notification.

Example:

```text
PAYMENT_FAILED
resource_type = subscription
resource_id   = ...
```

Clicking the notification must still pass normal authorization for the destination resource.

Notification authorization and resource authorization are separate checks.

---

# 17. Sensitive Data Policy

Notification payloads must contain only the information necessary to:

- render the notification;
- identify the relevant CEOPRO resource;
- navigate to the relevant administrative page;
- support operational investigation.

Do not place unnecessary payment or personal information inside the notification payload.

For Stripe events, identifiers such as these may be appropriate:

```text
subscriptionId
stripeEventId
stripeInvoiceId
paymentIntentId
failureReason
```

but secrets or sensitive payment credentials must never be stored.

Never store:

```text
Stripe secret keys
full card numbers
CVC
raw authentication credentials
access tokens
```

---

# 18. Severity Does Not Change Authorization

Severity controls presentation and operational importance.

It must not widen the audience.

For example:

```text
PAYMENT_FAILED
severity = CRITICAL
```

does not mean:

```text
send to everybody
```

Recipient authorization remains:

```text
Owner
+
admins authorized for billing
```

regardless of severity.

---

# 19. Source Tenant Isolation

The source/customer tenant is stored for context:

```text
source_tenant_id
```

Example:

```text
Acme payment failed
```

may create:

```text
platform_tenant_id = CEOPRO platform
source_tenant_id   = Acme
```

`source_tenant_id` must never be used to select ordinary tenant users for the Platform Admin inbox.

It exists so platform staff can understand:

```text
Which customer caused this event?
```

not:

```text
Who should receive this notification?
```

---

# 20. Worker Responsibilities

The Platform Notification Worker is responsible for:

```text
outbox event
    ↓
load event definition
    ↓
determine required permission
    ↓
resolve canonical platform tenant
    ↓
resolve authorized recipients
    ↓
create platform_notification
    ↓
create receipts
    ↓
mark outbox delivered
```

Business modules are not responsible for recipient resolution.

For example:

```text
Stripe module
→ produces PAYMENT_FAILED

Stripe module
→ does NOT query Platform Admin users
```

This maintains separation between business logic and notification delivery.

---

# 21. Explicit Non-Goals

The Platform Admin notification recipient policy does not:

- send notifications to ordinary customer users;
- replace tenant-facing notifications;
- replace `system_alerts`;
- replace `audit_logs`;
- grant resource permissions;
- grant Platform Admin access;
- automatically authorize users based only on role names;
- treat every Platform Admin as a recipient of every event.

---

# 22. Initial CEOPRO Rule for PAYMENT_FAILED

For the first implemented notification:

```text
PAYMENT_FAILED
```

the recipient rule is:

```text
Canonical CEOPRO platform membership
                +
active/verified membership
                +
authorized Platform Admin role
                +
notifications.read
                +
billing.read
```

with the Platform Owner included through the existing full-access owner policy.

Expected result:

```text
Platform Owner
→ RECEIVE

Platform Admin + billing.read
→ RECEIVE

Platform Admin without billing.read
→ DO NOT RECEIVE

Customer Owner
→ DO NOT RECEIVE

Customer Admin
→ DO NOT RECEIVE

Other customer user
→ DO NOT RECEIVE
```

---

# 23. Policy Summary

The final recipient rule is:

```text
                    PLATFORM EVENT
                          │
                          ▼
              Canonical platform tenant?
                          │
                         YES
                          ▼
             Active/verified membership?
                          │
                         YES
                          ▼
                  Platform Owner?
                    │          │
                   YES         NO
                    │          │
              RECEIVE          ▼
                         Authorized admin?
                               │
                              YES
                               ▼
                      notifications.read?
                               │
                              YES
                               ▼
                      Domain permission?
                               │
                              YES
                               ▼
                            RECEIVE
```

The fundamental CEOPRO rule is:

> **Roles establish the Platform Administration boundary. Permissions determine which platform events a user is allowed to receive.**

The worker must always fail closed rather than broadening the audience when recipient authorization is uncertain.
