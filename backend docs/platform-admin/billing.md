# Platform Billing API

## Base authorization
Every route is under `/platform-admin` and therefore requires authenticated user, valid tenant context, active membership, and `roleKey=owner` before the endpoint-specific permission.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/platform-admin/billing/tenants` | `billing.read` | List tenants for commercial administration. |
| GET | `/platform-admin/billing/subscriptions` | `subscriptions.read` | List customer subscriptions with current/scheduled plans and transition metadata. |
| GET | `/platform-admin/billing/plans` | `billing.read` | List managed standard plans, including inactive. |
| POST/PATCH | `/platform-admin/billing/plans...` | `billing.manage` | Create/update standard plans. |
| GET | `/platform-admin/billing/custom-plans` | `billing.read` | List accepted tenant-specific Custom Plans. |
| PATCH | `/platform-admin/billing/custom-plans/:id/status` | `billing.manage` | Enable/disable the plan definition only. |
| GET | `/platform-admin/billing/custom-quotes...` | `billing.read` | Read platform-wide Custom quotes. |
| POST/PATCH/actions | `/platform-admin/billing/custom-quotes...` | `billing.manage` | Create/edit/calculate/approve/send/reject quote workflow. |
| GET/PATCH | `/platform-admin/billing/pricing-policy` | read / `billing.pricing.manage` | Read/update automated pricing policy. |
| GET/POST/PATCH | `/platform-admin/billing/vendor-rates...` | read / `billing.pricing.manage` | Vendor cost-rate administration. |
| GET/POST/PATCH/link | `/platform-admin/billing/promo-codes...` | read / `billing.manage` | Promo-code administration. |
| GET/POST/PATCH | `/platform-admin/billing/features...` | read / `billing.manage` | Feature catalog administration. |
| GET/POST/PATCH | `/platform-admin/billing/plans/:plan_id/features...` | read / `billing.manage` | Plan-feature linking and limits. |

## Subscription list semantics
The backend derives `transitionType` by comparing current `plan` with `scheduledPlan`. It also returns `scheduledEffectiveAt` (`currentPeriodEnd` when a scheduled target exists) and `transitionHasEntitlementLoss`. The frontend therefore shows a future Custom Plan as **Scheduled**, not as the current plan.
