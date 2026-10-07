import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type Stripe from "stripe";

export type LifecyclePlan = {
  id: string;
  name: string;
  stripePriceId: string;
  limit: number;
};

export type LifecycleFixture = {
  run: string;
  tenantId: string;
  billingFeatureId: string;
  lifetimeFeatureId: string;
  billingFeatureCode: string;
  lifetimeFeatureCode: string;
  stripeProductId: string;
  plans: LifecyclePlan[];
};

function databaseUrl(): string | undefined {
  return (
    process.env.SUBSCRIPTION_TEST_DATABASE_URL?.trim() ||
    process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim()
  );
}

export function assertLifecycleTestEnvironment(): void {
  const dbUrl = databaseUrl();
  const stripeKey = process.env.STRIPE_SECRET_KEY?.trim();

  assert.ok(
    dbUrl,
    "SUBSCRIPTION_TEST_DATABASE_URL or CUSTOM_PLAN_TEST_DATABASE_URL is required and must point at a disposable migrated database.",
  );
  assert.match(
    dbUrl,
    /test/i,
    "Refusing to run lifecycle tests unless the database URL contains 'test'. Use a disposable test database.",
  );
  assert.ok(stripeKey, "STRIPE_SECRET_KEY is required for subscription lifecycle tests.");
  assert.ok(
    stripeKey.startsWith("sk_test_"),
    "Refusing to run subscription lifecycle tests unless STRIPE_SECRET_KEY starts with sk_test_.",
  );

  process.env.DATABASE_URL = dbUrl;
  process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
  process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
  process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";
  process.env.STRIPE_USE_TEST_CLOCK = "false";
}

export async function loadLifecycle() {
  assertLifecycleTestEnvironment();
  const [
    db,
    stripeModule,
    webhookModule,
    subscriptionServiceModule,
    plansServiceModule,
    usageModule,
    subscriptionRepoModule,
  ] = await Promise.all([
    import("../../../src/config/database.js"),
    import("../../../src/modules/subscription/client/payment-providers/stripe/stripe.client.js"),
    import("../../../src/modules/subscription/service/stripe-webhook.service.js"),
    import("../../../src/modules/subscription/service/subscription.service.js"),
    import("../../../src/modules/subscription/service/plans.service.js"),
    import("../../../src/modules/features/repo/usage.repo.js"),
    import("../../../src/modules/subscription/repo/subscription.repo.js"),
  ]);

  return {
    prisma: db.prisma,
    stripeService: stripeModule.stripeService,
    stripe: stripeModule.stripeService.stripe,
    webhookService: webhookModule.webhookService,
    cancelSubscriptionService: subscriptionServiceModule.cancelSubscriptionService,
    undoCancelSubscriptionService: subscriptionServiceModule.undoCancelSubscriptionService,
    createSubscriptionRecoveryService:
      subscriptionServiceModule.createSubscriptionRecoveryService,
    checkoutService: subscriptionServiceModule.checkoutService,
    cancelScheduledPlanChangeService:
      subscriptionServiceModule.cancelScheduledPlanChangeService,
    changePlanService: plansServiceModule.changePlanService,
    getRemainingUsage: usageModule.getRemainingUsage,
    subscriptionRepo: subscriptionRepoModule.default,
  };
}

export async function createLifecycleFixture(options?: {
  planLimits?: number[];
  priceAmountsUsd?: number[];
}): Promise<LifecycleFixture> {
  const { prisma, stripe } = await loadLifecycle();
  const run = randomUUID().slice(0, 8);
  const planLimits = options?.planLimits ?? [100];
  const priceAmountsUsd = options?.priceAmountsUsd ?? planLimits.map((_, i) => 10 + i * 5);

  assert.equal(
    planLimits.length,
    priceAmountsUsd.length,
    "planLimits and priceAmountsUsd must have the same length",
  );

  const product = await stripe.products.create({
    name: `CEOPRO Subscription Lifecycle ${run}`,
    metadata: { ceoproTestRun: run, purpose: "subscription-lifecycle" },
  });

  const tenant = await prisma.company.create({
    data: {
      businessName: `Subscription Lifecycle ${run}`,
      businessType: "test",
      countryCode: "JO",
      primaryCurrency: "USD",
    },
  });

  const billingFeatureCode = `lifecycle_billing_${run}`;
  const lifetimeFeatureCode = `lifecycle_lifetime_${run}`;

  const billingFeature = await prisma.feature.create({
    data: {
      code: billingFeatureCode,
      name: `Lifecycle Billing ${run}`,
      name_ar: `Lifecycle Billing ${run}`,
      type: "limit",
      unit: "count",
      unit_ar: "count",
      aggregationType: "sum",
      resetCycle: "billing_period",
    },
  });

  const lifetimeFeature = await prisma.feature.create({
    data: {
      code: lifetimeFeatureCode,
      name: `Lifecycle Lifetime ${run}`,
      name_ar: `Lifecycle Lifetime ${run}`,
      type: "limit",
      unit: "count",
      unit_ar: "count",
      aggregationType: "sum",
      resetCycle: "lifetime",
    },
  });

  const plans: LifecyclePlan[] = [];

  for (let i = 0; i < planLimits.length; i += 1) {
    const amount = priceAmountsUsd[i];
    const price = await stripe.prices.create({
      product: product.id,
      currency: "usd",
      unit_amount: Math.round(amount * 100),
      recurring: { interval: "month", interval_count: 1 },
      metadata: { ceoproTestRun: run, planIndex: String(i) },
    });

    const plan = await prisma.plan.create({
      data: {
        name: `Lifecycle ${run}-${i}`,
        name_ar: `Lifecycle ${run}-${i}`,
        tierLevel: i + 1,
        planType: "standard",
        description: "Automated subscription lifecycle test plan",
        description_ar: "Automated subscription lifecycle test plan",
        price: amount,
        currency: "USD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month",
        trialPeriodValue: 0,
        paymentProviderProductId: product.id,
        billingOptions: [
          {
            period: "monthly",
            months: 1,
            intervalUnit: "month",
            intervalCount: 1,
            discountPercent: 0,
            amount,
            stripePriceId: price.id,
          },
        ],
        isActive: true,
      },
    });

    await prisma.planFeature.createMany({
      data: [
        {
          plan_id: plan.id,
          feature_id: billingFeature.id,
          limit_value: planLimits[i],
          metadata: { test: true, reset: "billing_period" },
        },
        {
          plan_id: plan.id,
          feature_id: lifetimeFeature.id,
          limit_value: 10,
          metadata: { test: true, reset: "lifetime" },
        },
      ],
    });

    await prisma.planPriceVersion.create({
      data: {
        planId: plan.id,
        stripePriceId: price.id,
        periodCode: "monthly",
        intervalUnit: "month",
        intervalCount: 1,
        amount,
        currency: "USD",
      },
    });

    plans.push({
      id: plan.id,
      name: plan.name,
      stripePriceId: price.id,
      limit: planLimits[i],
    });
  }

  return {
    run,
    tenantId: tenant.id,
    billingFeatureId: billingFeature.id,
    lifetimeFeatureId: lifetimeFeature.id,
    billingFeatureCode,
    lifetimeFeatureCode,
    stripeProductId: product.id,
    plans,
  };
}

export async function createCustomerWithPaymentMethod(args: {
  run: string;
  tenantId: string;
  testClockId?: string;
  paymentMethodId?: string;
}) {
  const { stripe } = await loadLifecycle();
  const paymentMethodId =
    args.paymentMethodId ??
    process.env.STRIPE_E2E_VALID_PAYMENT_METHOD ??
    "pm_card_visa";

  const customer = await stripe.customers.create({
    email: `subscription-${args.run}@example.test`,
    name: `CEOPRO Subscription ${args.run}`,
    metadata: { tenantId: args.tenantId, ceoproTestRun: args.run },
    ...(args.testClockId ? { test_clock: args.testClockId } : {}),
  });

  const paymentMethod = await stripe.paymentMethods.attach(paymentMethodId, {
    customer: customer.id,
  });

  await stripe.customers.update(customer.id, {
    invoice_settings: { default_payment_method: paymentMethod.id },
  });

  return { customer, paymentMethodId: paymentMethod.id };
}

export function makeLifecycleEvent<T extends Stripe.Event.Type>(args: {
  id?: string;
  type: T;
  object: any;
}): Stripe.Event {
  const now = Math.floor(Date.now() / 1000);
  return {
    id: args.id ?? `evt_lifecycle_${randomUUID().replaceAll("-", "")}`,
    object: "event",
    api_version: null,
    created: now,
    data: { object: args.object },
    livemode: false,
    pending_webhooks: 0,
    request: { id: null, idempotency_key: null },
    type: args.type,
  } as unknown as Stripe.Event;
}

export async function waitForLifecycle<T>(
  label: string,
  load: () => Promise<T>,
  predicate: (value: T) => boolean,
  timeoutMs = 120_000,
  intervalMs = 2_000,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const value = await load();
    if (predicate(value)) return value;
    if (Date.now() >= deadline) throw new Error(`Timed out waiting for ${label}`);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export async function deleteWebhookEvents(eventIds: string[]): Promise<void> {
  if (!eventIds.length) return;
  const { prisma } = await loadLifecycle();
  await prisma.payment_providerWebhookEvent.deleteMany({
    where: { payment_providerEventId: { in: eventIds } },
  });
}

export async function cleanupLifecycleFixture(
  fixture: LifecycleFixture,
  extra?: {
    stripeCustomerIds?: string[];
    stripeSubscriptionIds?: string[];
    stripeTestClockIds?: string[];
    eventIds?: string[];
  },
): Promise<void> {
  const { prisma, stripe } = await loadLifecycle();

  for (const subscriptionId of extra?.stripeSubscriptionIds ?? []) {
    try {
      const subscription = await stripe.subscriptions.retrieve(subscriptionId);
      if (subscription.status !== "canceled") {
        await stripe.subscriptions.cancel(subscriptionId);
      }
    } catch {}
  }

  for (const customerId of extra?.stripeCustomerIds ?? []) {
    try {
      await stripe.customers.del(customerId);
    } catch {}
  }

  for (const clockId of extra?.stripeTestClockIds ?? []) {
    try {
      const api = stripe.testHelpers.testClocks as any;
      if (typeof api.del === "function") await api.del(clockId);
    } catch {}
  }

  if (extra?.eventIds?.length) {
    await prisma.payment_providerWebhookEvent.deleteMany({
      where: { payment_providerEventId: { in: extra.eventIds } },
    });
  }

  const subscriptions = await prisma.subscription.findMany({
    where: { tenantId: fixture.tenantId },
    select: { id: true },
  });
  const subscriptionIds = subscriptions.map((row) => row.id);

  if (subscriptionIds.length) {
    await prisma.promoCodeRedemption.deleteMany({
      where: { subscriptionId: { in: subscriptionIds } },
    });
    await prisma.paymentTransaction.deleteMany({
      where: { subscriptionId: { in: subscriptionIds } },
    });
    await prisma.subscriptionUsage.deleteMany({
      where: { subscription_id: { in: subscriptionIds } },
    });
    await prisma.subscription.deleteMany({
      where: { id: { in: subscriptionIds } },
    });
  }

  await prisma.platformNotificationOutbox.deleteMany({
    where: { tenantId: fixture.tenantId },
  });
  await prisma.tenantNotificationOutbox.deleteMany({
    where: { tenantId: fixture.tenantId },
  });

  const planIds = fixture.plans.map((plan) => plan.id);
  if (planIds.length) {
    await prisma.planFeature.deleteMany({ where: { plan_id: { in: planIds } } });
    await prisma.planPriceVersion.deleteMany({ where: { planId: { in: planIds } } });
    await prisma.plan.deleteMany({ where: { id: { in: planIds } } });
  }

  await prisma.feature.deleteMany({
    where: { id: { in: [fixture.billingFeatureId, fixture.lifetimeFeatureId] } },
  });
  await prisma.tenantUser.deleteMany({ where: { tenantId: fixture.tenantId } });
  await prisma.company.deleteMany({ where: { id: fixture.tenantId } });

  try {
    const prices = await stripe.prices.list({
      product: fixture.stripeProductId,
      limit: 100,
    });
    for (const price of prices.data) {
      if (price.active) await stripe.prices.update(price.id, { active: false });
    }
    await stripe.products.update(fixture.stripeProductId, { active: false });
  } catch {}
}

export async function disconnectLifecycleDb(): Promise<void> {
  const { prisma } = await loadLifecycle();
  await prisma.$disconnect();
}
