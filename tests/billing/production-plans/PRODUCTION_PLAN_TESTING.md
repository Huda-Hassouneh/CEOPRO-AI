# CEOPRO Production Plan / Bootstrap Verification

This suite verifies the standard-plan infrastructure against a disposable PostgreSQL database and Stripe TEST mode.

## Important distinction

The repository currently does **not** define the final real production standard-plan catalog (names, prices, feature limits, etc.) in a dedicated production manifest/bootstrap.

Therefore groups 27–32 use temporary **production-shaped fixtures** to verify the machinery. Group 33 intentionally checks whether the missing production catalog/bootstrap has been implemented and will fail until it exists.

Do not copy test fixture prices into production as business configuration.

## Safety

Use only:

- a disposable migrated database whose URL contains `test`;
- a Stripe `sk_test_...` key.

The runner refuses other environments.

The backend server and Stripe CLI listener are not required.

## PowerShell

```powershell
$env:PRODUCTION_PLAN_TEST_DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
$env:DATABASE_URL=$env:PRODUCTION_PLAN_TEST_DATABASE_URL
$env:STRIPE_SECRET_KEY="sk_test_..."

npm run prisma:migrate:test
npm run test:plans:production
```

## Groups

1. `27 - Production catalog boundary`
   - public catalog includes only active standard tenant-neutral plans;
   - inactive standard plans are hidden;
   - tenant-private custom plans are hidden.

2. `28 - Stripe bootstrap idempotency`
   - shared CEOPRO Stripe Product is created once;
   - rerun fails fast instead of creating another product;
   - AppConfig mapping stays stable.

3. `29 - Standard-plan pricing + mappings`
   - plan creation creates real Stripe TEST Prices;
   - monthly/yearly amounts are exact;
   - DB billing options and `plan_price_versions` agree with Stripe.

4. `30 - Public/managed catalog visibility`
   - active standard plan is public;
   - inactive plan is retained for owner management but not public checkout.

5. `31 - Standard-plan checkout`
   - checkout uses the server-owned Stripe Price;
   - amount/currency agree with the plan;
   - tenant metadata is preserved.

6. `32 - Subscription + entitlements`
   - real Stripe TEST subscription maps back to the exact standard plan;
   - webhook synchronization activates the local subscription;
   - plan features create usage allocations.

7. `33 - Production bootstrap safety`
   - development seed remains visibly synthetic;
   - bootstrap commands do not run `prisma:seed`;
   - Stripe product bootstrap does not seed tenants/users;
   - a dedicated `bootstrap:plans` command must exist;
   - an explicit production catalog manifest/config must exist.

## Expected first run

Groups 27–32 should validate the existing standard-plan machinery.

Group 33 is expected to identify the current release gap if the project still has only:

```text
bootstrap:stripe
```

and no dedicated production standard-plan bootstrap/catalog.

That is intentional. Do not weaken the test. Implement the production plan bootstrap next, then rerun until 7/7 passes.

## After group 33 is fixed

The release path should become conceptually:

```text
empty production DB
  -> prisma migrate deploy
  -> bootstrap:features
  -> bootstrap:stripe
  -> bootstrap:plans
  -> bootstrap:owner/admin as required
  -> verify public catalog
  -> standard checkout smoke test
```

Development fixtures from `prisma/seed.ts` must not be used for production bootstrap.
