# Subscription and Feature Management Backend

## 1. Overview

This backend provides subscription, billing, plan, promotion, feature-entitlement, usage, invoice, and Stripe integration capabilities for a multi-tenant application.

The service is built with:

- Node.js
- TypeScript
- Express.js
- PostgreSQL
- Prisma
- Stripe
- Zod
- JWT authentication

The system is designed around tenant isolation. Authenticated users operate inside a tenant context, permissions are checked before protected actions are executed, and subscription/payment records are associated with the correct company or tenant.

The main responsibilities of the backend are:

- Manage subscription plans.
- Manage promotional codes.
- Link promotional codes to plans.
- Create and manage subscriptions.
- Create Stripe checkout sessions.
- Process Stripe webhooks.
- Store payment transactions and invoices safely.
- Manage product features and plan entitlements.
- Track feature usage for subscription limits.
- Enforce tenant membership and permissions.
- Validate incoming requests before business logic is executed.
- Return consistent API errors without exposing internal provider details.

---

## 2. Project Structure

```text
.
├── prisma/
│   ├── schema.prisma
│   └── migrations/
├── scripts/
│   ├── generate-mock-token.ts
│   ├── verify-route-contract.mjs
│   └── verify-security-regressions.mjs
├── src/
│   ├── config/
│   ├── constants/
│   ├── DTO/
│   ├── errors/
│   ├── middleware/
│   ├── modules/
│   │   ├── features/
│   │   └── subscription/
│   ├── types/
│   ├── utils/
│   ├── validators/
│   ├── app.ts
│   └── server.ts
├── tests/
├── .env.example
├── package.json
├── prisma7.config.ts
└── tsconfig.json
```

### Important folders

`src/modules/subscription`

Contains plan management, promo codes, subscriptions, invoices, payment-provider integration, repositories, services, and subscription controllers.

`src/modules/features`

Contains feature definitions, plan-feature relationships, usage tracking, entitlement checks, and feature-related services.

`src/DTO`

Contains Zod schemas used to validate request bodies, parameters, and queries.

`src/validators`

Contains authentication, tenant validation, authorization, body validation, query validation, parameter validation, webhook validation, and entitlement validation.

`src/errors`

Contains application error codes and their HTTP/message definitions.

`src/utils`

Contains shared utilities such as Stripe currency conversion, checkout utilities, token helpers, HTTP response helpers, and webhook helpers.

`prisma`

Contains the database schema and migrations.

---

## 3. Requirements

Install the following before starting the project:

- Node.js compatible with the dependencies in `package.json`
- npm
- PostgreSQL
- Stripe test or production account

For local development, Stripe test mode should be used.

---

## 4. Installation

Clone or extract the project, then install dependencies:

```bash
npm install
```

For reproducible environments where the lock file must be followed exactly:

```bash
npm ci
```

---

## 5. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then configure the values in `.env`.

Example:

```env
PORT=5000
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE

JWT_SECRET=replace-with-a-long-random-secret
JWT_REFRESH_SECRET=replace-with-a-different-long-random-secret
JWT_ACCESS_EXPIRES_IN=1h
JWT_REFRESH_EXPIRES_IN=7d

STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_SECRET_WEBHOOK=whsec_replace_me

SUCCESS_SUBSCRIPTION_URL=http://localhost:5173
FAILED_SUBSCRIPTION_URL=http://localhost:5173

CORS_ORIGINS=http://localhost:5173

JSON_BODY_LIMIT=1mb
MAX_UPLOAD_BYTES=10485760

PROMO_FIXED_AMOUNT_CURRENCY=USD

STRIPE_USE_TEST_CLOCK=false
# STRIPE_TEST_CLOCK_ID=clock_replace_me

AI_SERVICE_URL=http://localhost:8000
```

### Environment variables

#### `PORT`

HTTP port used by the Express server.

Default:

```text
5000
```

#### `DATABASE_URL`

PostgreSQL connection string used by Prisma.

#### `JWT_SECRET`

Secret used to verify access tokens.

The authentication middleware only accepts tokens signed with `HS256`.

#### `JWT_REFRESH_SECRET`

Separate secret used for refresh-token operations.

It should not be the same value as `JWT_SECRET`.

#### `JWT_ACCESS_EXPIRES_IN`

Access-token lifetime.

#### `JWT_REFRESH_EXPIRES_IN`

Refresh-token lifetime.

#### `STRIPE_SECRET_KEY`

Stripe server-side secret key.

Use a test key during development.

#### `STRIPE_SECRET_WEBHOOK`

Stripe webhook signing secret used to verify that incoming webhook requests were sent by Stripe.

#### `SUCCESS_SUBSCRIPTION_URL`

Frontend URL used after a successful Stripe checkout.

#### `FAILED_SUBSCRIPTION_URL`

Frontend URL used when checkout is cancelled or cannot continue.

#### `CORS_ORIGINS`

Comma-separated list of frontend origins allowed to call the API.

Example:

```env
CORS_ORIGINS=http://localhost:5173,https://app.example.com
```

#### `JSON_BODY_LIMIT`

Maximum JSON request-body size.

#### `MAX_UPLOAD_BYTES`

Maximum accepted file size for upload-based features.

#### `PROMO_FIXED_AMOUNT_CURRENCY`

Currency used for fixed-amount Stripe coupons.

The value must match the currency of plans to which the fixed-amount promotion is linked and must be supported by the configured Stripe account.

#### `STRIPE_USE_TEST_CLOCK`

Enables Stripe test-clock behavior in supported development/testing flows.

#### `STRIPE_TEST_CLOCK_ID`

Optional existing Stripe test clock ID.

#### `AI_SERVICE_URL`

Base URL of the external AI service used by feature-specific integrations.

---

## 6. Database Setup

The project uses Prisma with PostgreSQL.

Generate the Prisma client:

```bash
npm run prisma:generate
```

Validate the Prisma schema:

```bash
npm run prisma:validate
```

Apply the included migrations using the Prisma migration command appropriate for the environment.

For development:

```bash
npx prisma migrate dev --config prisma7.config.ts
```

For production/deployment:

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

Important database entities include:

- Company
- User
- TenantUser
- SystemRole
- Plan
- PromoCode
- PromoCodePlan
- Subscription
- PaymentTransaction
- PromoCodeRedemption
- Payment-provider webhook event
- Feature
- PlanFeature
- SubscriptionUsage

---

## 7. Running the Application

### Development

```bash
npm run dev
```

This starts the TypeScript application using `tsx` in watch mode.

Default local URL:

```text
http://localhost:5000
```

Health/root endpoint:

```http
GET /
```

Response:

```json
{
  "message": "CEO PRO API is running..."
}
```

### Production build

```bash
npm run build
```

This performs Prisma client generation and TypeScript compilation.

Then start the compiled application:

```bash
npm start
```

---

## 8. Authentication Model

Protected endpoints expect a Bearer token:

```http
Authorization: Bearer <token>
```

The token is verified using `JWT_SECRET` and `HS256`.

The expected authenticated-user payload includes at least:

```json
{
  "id": "USER_UUID",
  "email": "user@example.com",
  "tenant_id": "TENANT_UUID"
}
```

Authentication alone is not enough for tenant operations.

After token verification, the backend verifies that:

1. The token contains a user ID.
2. The token contains a tenant ID.
3. The user has an active membership in that tenant.
4. The tenant membership has a valid role.
5. The role grants the permission required by the endpoint.

This prevents a valid token from being used to access another tenant only by changing request data.

---

## 9. Permission Model

Permissions are read from the tenant user's role.

The main permissions used by the current API are:

### `all`

Full permission for high-level catalog or administrative actions.

### `manage_catalog`

Allows management of subscription plans, features, plan-feature mappings, and subscription-plan operations.

### `manage_billing`

Allows billing-specific actions such as validating promotional codes where configured.

The authorization check also treats:

```json
{
  "all": true
}
```

as permission to perform any protected action.

---

# 10. User Stories

## User Story 1 - Public user views available plans

As a visitor or frontend application, I want to retrieve subscription plans so that available packages can be displayed before checkout.

### Endpoint

```http
GET /subscription/plans
```

This endpoint is public.

### Flow

1. Client requests available plans.
2. Backend reads plan information from the database.
3. Plan information is returned to the client.

Authentication is not required for this endpoint.

---

## User Story 2 - Authorized catalog administrator creates a plan

As a tenant user with catalog administration rights, I want to create subscription plans so that customers can subscribe to different packages.

### Endpoint

```http
POST /subscription/plans
```

### Required access

- Valid JWT
- Active tenant membership
- `all` permission

### Example request

```json
{
  "name": "growth",
  "name_ar": "النمو",
  "tierLevel": 2,
  "description": "Growth subscription",
  "description_ar": "اشتراك النمو",
  "price": 49.99,
  "currency": "USD",
  "billingIntervalValue": 1,
  "billingIntervalUnit": "month",
  "trialPeriodValue": 7,
  "isActive": true,
  "billingOptions": [
    {
      "period": "monthly",
      "months": 1,
      "discountPercent": 0
    },
    {
      "period": "yearly",
      "months": 12,
      "discountPercent": 15
    }
  ]
}
```

### Validation approach

The plan request is validated before reaching the controller.

Examples of enforced rules:

- Currency must be a 3-letter uppercase code.
- Price cannot be negative.
- Price supports up to two decimal places.
- Billing interval must be valid.
- Billing options require positive month values.
- Percentage discounts cannot exceed 100%.

---

## User Story 3 - Authorized catalog administrator updates a plan

As a catalog administrator, I want to update an existing plan without replacing the entire record.

### Endpoint

```http
PATCH /subscription/plans/:id
```

### Required access

- Valid JWT
- Active tenant membership
- `all` permission

The route ID must be a valid UUID, and at least one supported field must be supplied in the request body.

---

## User Story 4 - Administrator creates a promotional code

As an authorized administrator, I want to create promotional codes with usage and date restrictions.

### Endpoint

```http
POST /subscription/promo-codes
```

### Required access

- Valid JWT
- Active tenant membership
- `all` permission

### Example percentage promotion

```json
{
  "code": "WELCOME20",
  "discountType": "percentage",
  "discountValue": 20,
  "maxUses": 100,
  "maxUsesPerUser": 1,
  "startsAt": "2026-01-01T00:00:00.000Z",
  "expiresAt": "2026-12-31T23:59:59.000Z",
  "isActive": true
}
```

### Business rules

- Promo codes are normalized to uppercase.
- Percentage discounts cannot exceed 100%.
- Expiration must be later than the start date.
- Per-user usage cannot exceed total usage.
- Usage is tracked during redemption.
- Fixed-amount promotions require currency compatibility with the plan/payment provider.

---

## User Story 5 - Administrator links a promo code to a plan

As an administrator, I want a promotion to apply only to selected plans.

### Endpoint

```http
POST /subscription/promo-codes/:promoCodeId/plans/:planId
```

### Required access

- Valid JWT
- Active tenant membership
- `all` permission

Both identifiers must be valid UUID values.

For fixed-amount promotions, the backend also verifies payment-provider currency compatibility before allowing the relationship.

---

## User Story 6 - Billing user validates a promo code before checkout

As a billing user, I want to validate a promotion against a selected plan before creating the checkout session.

### Endpoint

```http
POST /subscription/promo-codes/validate
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_billing` or `all`

### Request

```json
{
  "code": "WELCOME20",
  "planId": "PLAN_UUID"
}
```

### Validation includes

- Promo exists.
- Promo is active.
- Current time is within the configured start/end period.
- Promo is linked to the requested plan where required.
- Total usage limit has not been reached.
- Tenant/user redemption limit has not been reached.
- Discount configuration is valid.

---

## User Story 7 - Tenant starts a subscription checkout

As an authorized tenant user, I want to subscribe to a plan and receive a hosted payment checkout session.

### Endpoint

```http
POST /subscription/checkout
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

### Request

```json
{
  "planId": "PLAN_UUID",
  "billing_period": "monthly",
  "payment_method": "stripe",
  "promoCode": "WELCOME20"
}
```

`promoCode` is optional.

Accepted billing periods:

```text
monthly
three-months
six-months
yearly
```

Accepted values at request-schema level for `payment_method` are:

```text
card
stripe
googlePay
paypal
```

The service only executes providers that are implemented. Unsupported providers are rejected with a controlled application error rather than being silently redirected to Stripe.

### Checkout approach

1. Authenticate user.
2. Verify tenant membership.
3. Verify permission.
4. Validate checkout payload.
5. Load selected plan.
6. Resolve the selected billing period.
7. Validate promotion when provided.
8. Resolve or create the Stripe customer using tenant-aware metadata.
9. Create the Stripe checkout session.
10. Return checkout information to the frontend.

### Tenant-aware Stripe customer handling

Stripe customers are associated with tenant context.

When tenant information is available, customer lookup does not fall back to a user-only match. This avoids reusing one Stripe customer across multiple tenants owned or accessed by the same user.

---

## User Story 8 - Tenant views the current subscription

As a tenant user, I want to retrieve my tenant's current subscription state.

### Endpoint

```http
GET /subscription/current
```

### Required access

- Valid JWT
- Active tenant membership

The subscription is resolved using tenant context rather than trusting a tenant identifier supplied by the client.

---

## User Story 9 - Tenant changes the current plan

As an authorized tenant user, I want to change the active subscription plan.

### Endpoint

```http
PATCH /subscription/current/plan
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

### Example request

```json
{
  "planId": "NEW_PLAN_UUID",
  "billing_period": "yearly"
}
```

The request is validated before subscription/provider operations are performed.

---

## User Story 10 - Tenant schedules subscription cancellation

As an authorized tenant user, I want to cancel the current subscription.

### Endpoint

```http
PATCH /subscription/current/cancel
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

The cancellation flow synchronizes local subscription state with the payment-provider state instead of only modifying the database record.

---

## User Story 11 - Tenant reverses a scheduled cancellation

As an authorized tenant user, I want to undo a previously scheduled cancellation.

### Endpoint

```http
PATCH /subscription/current/cancel/undo
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

---

## User Story 12 - Tenant views invoices

As a tenant user, I want to retrieve invoices associated with my tenant subscription.

### Endpoint

```http
GET /subscription/invoices
```

### Required access

- Valid JWT
- Active tenant membership

Invoice access is tenant-scoped.

---

## User Story 13 - Administrator manages system features

As a catalog administrator, I want to define capabilities that can later be assigned to plans.

### Endpoints

```http
GET /features
GET /features/:id
POST /features
PATCH /features/:id
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

### Example feature

```json
{
  "code": "ai_pricing",
  "name": "AI Pricing",
  "name_ar": "التسعير بالذكاء الاصطناعي",
  "description": "AI pricing recommendation requests",
  "description_ar": "طلبات توصية التسعير",
  "type": "limit",
  "unit": "request",
  "unit_ar": "طلب",
  "aggregation_type": "sum",
  "reset_cycle": "billing_period"
}
```

### Feature types

`boolean`

Represents access that is either enabled or disabled for the plan.

`limit`

Represents a measurable entitlement such as number of requests, documents, seats, or another usage metric.

### Reset cycles

`billing_period`

Usage belongs to the current subscription billing period and resets when a new period is allocated.

`lifetime`

Usage remains cumulative across billing periods.

---

## User Story 14 - Administrator links a feature to a plan

As a catalog administrator, I want to control which features are included in each subscription plan.

### Get features assigned to a plan

```http
GET /plans/:plan_id/features
```

### Link a feature to a plan

```http
POST /plans/:plan_id/features
```

Example:

```json
{
  "feature_id": "FEATURE_UUID",
  "limit_value": 1000
}
```

`limit_value: null` represents unlimited usage where supported.

### Update the plan's feature limit

```http
PATCH /plans/:plan_id/features/:feature_id
```

Example:

```json
{
  "limit_value": 5000
}
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

---

## User Story 15 - Tenant views subscription usage

As a tenant user with catalog access, I want to view current feature consumption against subscription limits.

### Endpoint

```http
GET /subscriptions/current/usage
```

### Required access

- Valid JWT
- Active tenant membership
- `manage_catalog` or `all`

The usage system distinguishes between billing-period and lifetime features.

Billing-period usage is associated with the subscription's current provider period. Lifetime usage remains cumulative and is not discarded when a billing period changes.

---

## User Story 16 - Stripe sends a webhook

As the payment provider, Stripe needs to notify the backend when subscription/payment state changes.

### Endpoint

```http
POST /stripe/webhooks
```

This route is intentionally registered before the normal JSON parser.

### Why raw request handling is used

Stripe webhook signature validation requires the exact request body sent by Stripe.

The endpoint therefore uses:

```text
express.raw({ type: "application/json" })
```

before validating the Stripe signature.

### Webhook flow

1. Receive raw Stripe request.
2. Verify the Stripe signature using `STRIPE_SECRET_WEBHOOK`.
3. Resolve the event.
4. Prevent unsafe duplicate processing where the event or related transaction has already been handled.
5. Synchronize local subscription/payment state.
6. Allocate/update feature-usage periods when subscription state changes require it.
7. Persist payment or invoice information with idempotent identifiers.

Invalid webhook signatures are rejected before event business logic executes.

---

# 11. Subscription and Entitlement Approach

The subscription system separates plan configuration from tenant subscription state.

A plan describes what can be purchased.

A subscription describes what a tenant currently owns.

A plan-feature relationship describes which capabilities belong to that plan and what limits apply.

A subscription-usage record tracks what the tenant has consumed.

### Entitled subscription states

Entitlement checks use shared subscription-status rules instead of each feature deciding independently what an active subscription means.

The access-granting states include:

```text
active
trialing
```

This ensures trial subscriptions can receive the same feature-entitlement behavior where intended.

---

# 12. Usage Allocation Approach

Usage is tracked according to each feature's reset behavior.

## Billing-period feature

Example:

```text
AI requests: 1,000 per month
```

The backend creates or updates usage records for the current subscription period.

When Stripe moves the subscription into a new billing period, a new period-specific allocation can be used instead of reusing the previous period's consumption.

## Lifetime feature

Example:

```text
Maximum 10 imported workspaces for the lifetime of the subscription
```

Lifetime usage is not filtered only by the current billing period. This prevents historical lifetime consumption from disappearing after a renewal.

---

# 13. Stripe Payment Approach

Stripe is treated as an external payment provider rather than the source of all application authorization.

The application database remains responsible for tenant relationships, roles, plan configuration, usage, and application-level permissions.

Stripe is responsible for provider-side billing objects and payment lifecycle events.

### Amount conversion

Application prices are represented as major currency units.

Before provider requests are created, shared currency utilities convert amounts to the format expected by Stripe.

Do not manually multiply monetary values inside controllers or services. Provider amount conversion should remain centralized.

### Currency behavior

The plan schema accepts ISO-style three-letter uppercase currency codes.

Example:

```json
{
  "currency": "USD"
}
```

A currency being valid for the application does not automatically guarantee that the configured Stripe account can process it.

The provider can reject unsupported currencies or unsupported account/currency combinations. Such errors are handled by the backend and are not returned to the client as raw Stripe exception details.

For production deployments, supported application currencies should be aligned with the currencies enabled by the payment provider.

---

# 14. Promo Code Approach

Promo codes are application-level records that can also be linked to Stripe coupon behavior where required.

The design supports:

- Percentage discounts.
- Fixed-amount discounts.
- Start and expiration dates.
- Active/inactive state.
- Total usage limit.
- Per-user/tenant usage limit.
- Plan-specific relationships.

Promo consumption is performed with transactional protection so usage limits are not enforced only through an unsafe read-then-write sequence.

Fixed-amount promotions require explicit currency handling because a fixed monetary discount has different meaning across currencies.

---

# 15. Payment Transaction Idempotency

Payment-provider events may be retried.

The backend therefore avoids assuming every webhook or invoice event will arrive only once.

Payment transactions use stable provider/invoice identifiers and database uniqueness where appropriate.

Persistence uses idempotent create/update behavior so a retry does not create duplicate payment records for the same provider event or invoice.

This is important for:

- Stripe webhook retries.
- Network timeouts.
- Delayed webhook delivery.
- Application restarts during payment processing.

---

# 16. Tenant Isolation Approach

Tenant isolation is enforced using server-side context.

The backend does not trust a tenant ID supplied in a protected request body as proof of access.

For protected tenant operations:

1. JWT identifies the user and intended tenant context.
2. Database membership is checked.
3. Membership must be active.
4. Role permissions are loaded from the membership.
5. Repository/service operations use the validated tenant context.

Stripe customer lookup follows the same principle.

If the same person is a member of multiple companies, the system should not accidentally reuse one tenant's Stripe customer for another tenant simply because the user ID is the same.

---

# 17. Validation Approach

Zod is used at the HTTP boundary.

Separate middleware exists for:

- Request body validation.
- Route parameter validation.
- Query-string validation.

This keeps malformed input out of controller/service logic.

Examples:

- IDs are validated as UUIDs.
- Unknown checkout fields are rejected by strict schemas.
- Promo-code dates are validated.
- Percentage values are bounded.
- Feature codes follow a predictable lowercase naming convention.
- Usage limits must be non-negative integers or `null` where unlimited is allowed.

---

# 18. Error Handling Approach

The application uses centralized API error handling.

Expected errors are represented through application error codes and shared response helpers.

Unexpected errors are handled by the global error middleware.

This provides two benefits:

1. Clients receive a predictable JSON error format.
2. Internal exception details from PostgreSQL, Prisma, Stripe, JWT, or other dependencies are not exposed directly to the client.

The application also has a JSON 404 handler for unmatched routes.

Stripe/provider errors can be logged internally while the client receives an application-safe error response.

---

# 19. HTTP Security Controls

The Express application applies several baseline controls.

### Express signature disabled

```text
x-powered-by
```

is disabled.

### Security response headers

The application sets:

```text
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
X-Frame-Options: DENY
```

### CORS

Allowed origins are configured through `CORS_ORIGINS` rather than being hard-coded into the source.

### JSON request size

JSON body size is limited through `JSON_BODY_LIMIT`.

### File upload size

Upload size is limited through `MAX_UPLOAD_BYTES`.

---

# 20. Stripe Webhook Setup for Local Development

Run the API locally:

```bash
npm run dev
```

Then use the Stripe CLI to forward events to:

```text
http://localhost:5000/stripe/webhooks
```

Example Stripe CLI command:

```bash
stripe listen --forward-to localhost:5000/stripe/webhooks
```

Stripe CLI prints a webhook signing secret similar to:

```text
whsec_...
```

Place that value in:

```env
STRIPE_SECRET_WEBHOOK=whsec_...
```

Restart the application after changing the environment file.

---

# 21. Development Token Utility

A development token can be generated explicitly with:

```bash
npm run dev:token
```

Token generation is not part of normal server startup.

This avoids automatically printing authentication tokens whenever the application starts.

Use the utility only for local development/testing.

---

# 22. Testing and Validation

Run all configured tests and source checks:

```bash
npm test
```

This runs:

```text
unit tests
route-contract verification
security-regression verification
```

Run only unit tests:

```bash
npm run test:unit
```

Run route-contract checks:

```bash
npm run test:routes
```

Run security-regression checks:

```bash
npm run test:security
```

Run the complete validation pipeline:

```bash
npm run validate
```

The validation pipeline performs:

1. Prisma schema validation.
2. Prisma client generation/build.
3. TypeScript compilation.
4. Unit tests.
5. Route-contract checks.
6. Security-regression checks.

---

# 23. Route Summary

## General

```http
GET /
```

## Plans

```http
GET   /subscription/plans
POST  /subscription/plans
PATCH /subscription/plans/:id
```

## Promo Codes

```http
GET   /subscription/promo-codes
POST  /subscription/promo-codes
POST  /subscription/promo-codes/validate
PATCH /subscription/promo-codes/:id
POST  /subscription/promo-codes/:promoCodeId/plans/:planId
```

## Subscription

```http
POST  /subscription/
GET   /subscription/current
PATCH /subscription/current/cancel
PATCH /subscription/current/cancel/undo
PATCH /subscription/current/plan
POST  /subscription/checkout
GET   /subscription/invoices
```

## Feature Catalog

```http
GET   /features
GET   /features/:id
POST  /features
PATCH /features/:id
```

## Plan Features

```http
GET   /plans/:plan_id/features
POST  /plans/:plan_id/features
PATCH /plans/:plan_id/features/:feature_id
```

## Usage Dashboard

```http
GET /subscriptions/current/usage
```

## Stripe Webhook

```http
POST /stripe/webhooks
```

---

# 24. Recommended Local Startup Sequence

For a fresh environment:

```bash
npm ci
```

Create `.env`:

```bash
cp .env.example .env
```

Configure PostgreSQL, JWT, Stripe, frontend URLs, and CORS values.

Validate Prisma:

```bash
npm run prisma:validate
```

Generate Prisma client:

```bash
npm run prisma:generate
```

Apply migrations:

```bash
npx prisma migrate dev --config prisma7.config.ts
```

Run validation:

```bash
npm run validate
```

Start development server:

```bash
npm run dev
```

Verify:

```http
GET http://localhost:5000/
```

Then configure Stripe webhook forwarding if checkout/webhook functionality is being tested.

---

# 25. Production Deployment Notes

Before deploying:

1. Use production-grade random JWT secrets.
2. Keep `JWT_SECRET` and `JWT_REFRESH_SECRET` different.
3. Use a production PostgreSQL connection.
4. Apply migrations with `prisma migrate deploy`.
5. Configure the correct frontend URLs.
6. Configure only trusted CORS origins.
7. Use the appropriate Stripe production secret key.
8. Configure the production Stripe webhook endpoint and signing secret.
9. Verify enabled Stripe currencies before creating production plans.
10. Run `npm run validate` during CI/CD.
11. Do not enable Stripe test-clock behavior in normal production operation.
12. Do not expose `.env`, Stripe keys, JWT secrets, or database credentials to the frontend.

---

# 26. Design Principles Used in the System

The implementation follows these main principles:

- Keep HTTP routes thin and move business rules into services/repositories.
- Validate all external input at the API boundary.
- Authenticate before resolving tenant resources.
- Confirm active tenant membership before authorization.
- Apply explicit role permissions for protected operations.
- Scope tenant-owned data using server-validated tenant context.
- Keep Stripe/provider logic behind dedicated provider services.
- Verify webhook signatures before processing events.
- Design webhook/payment persistence for retries and duplicate delivery.
- Separate plan configuration from active subscription state.
- Separate feature definitions from plan-feature limits.
- Track billing-period and lifetime usage differently.
- Centralize subscription-state rules used for entitlement checks.
- Centralize currency conversion rather than duplicating provider math.
- Return stable application errors instead of leaking provider/database exceptions.
- Keep secrets and environment-specific configuration outside source code.
- Protect public API behavior with route-contract checks.

---

## Custom Plans and Cost-Aware Pricing

The subscription module now supports tenant-private custom plans through a quote-first workflow. Internal provider rates are stored separately, pricing floors are calculated server-side, and an accepted quote is converted into the existing `Plan` + `PlanFeature` architecture. The final approved customer price becomes `Plan.price` and the existing Stripe/subscription/webhook flow is reused.

Key backend locations:

- `src/modules/subscription/service/custom-plan-pricing.service.ts` - corrected pricing formulas
- `src/modules/subscription/service/custom-plan.service.ts` - quote lifecycle and quote-to-plan conversion
- `src/modules/subscription/repo/custom-plan.repo.ts` - persistence
- `src/modules/subscription/route/custom-plan.routes.ts` - HTTP surface
- `prisma/migrations/20260922060000_custom_plan_pricing/migration.sql` - schema extension

See `../CUSTOM_PLAN_IMPLEMENTATION.md` for the complete technical flow and `../CUSTOM_PLAN_BUSINESS_MODEL.md` for business rationale and user experience.
