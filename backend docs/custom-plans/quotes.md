# Legacy/Internal Custom Quote Management

## Base path
`/subscription/custom-plans/quotes`

These routes are authenticated tenant-context routes additionally restricted to the platform owner role.

| Method | Path | Permission |
|---|---|---|
| GET | `/subscription/custom-plans/quotes` | owner + `billing.read` |
| POST | `/subscription/custom-plans/quotes` | owner + `billing.manage` |
| GET | `/subscription/custom-plans/quotes/:id` | owner + `billing.manage` |
| PATCH | `/subscription/custom-plans/quotes/:id` | owner + `billing.manage` |
| POST | `/subscription/custom-plans/quotes/:id/calculate` | owner + `billing.manage` |
| POST | `/subscription/custom-plans/quotes/:id/approve` | owner + `billing.manage` |
| POST | `/subscription/custom-plans/quotes/:id/send` | owner + `billing.manage` |
| POST | `/subscription/custom-plans/quotes/:id/reject` | owner + `billing.manage` |

The platform UI primarily uses the clearer `/platform-admin/billing/custom-quotes*` aliases, which can resolve a tenant explicitly for platform-wide administration.
