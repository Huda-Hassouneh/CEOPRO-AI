import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type Stripe from "stripe";

export type StandardPlanFixture = {
  run: string;
  tenantId: string;
  userId: string;
  email: string;
  featureId: string;
  featureCode: string;
  stripeProductId: string;
  previousStripeProductId: string | null;
  planId: string;
  priceIds: string[];
};

function databaseUrl(): string | undefined {
  return (
    process.env.PRODUCTION_PLAN_TEST_DATABASE_URL?.trim() ||
    process.env.SUBSCRIPTION_TEST_DATABASE_URL?.trim() ||
    process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim()
  );
}

export function assertProductionPlanTestEnvironment(): void {
  const dbUrl = databaseUrl();
  const stripeKey = process.env.STRIPE_SECRET_KEY?.trim();

  assert.ok(
    dbUrl,
    "PRODUCTION_PLAN_TEST_DATABASE_URL, SUBSCRIPTION_TEST_DATABASE_URL, or CUSTOM_PLAN_TEST_DATABASE_URL is required.",
  );
  assert.match(
    dbUrl,
    /test/i,
    "Refusing to run production-plan verification unless the database URL contains 'test'. Use a disposable test database.",
  );
  assert.ok(stripeKey, "STRIPE_SECRET_KEY is required for production-plan verification.");
  assert.ok(
    stripeKey.startsWith("sk_test_"),
    "Refusing to run production-plan verification unless STRIPE_SECRET_KEY starts with sk_test_.",
  );

  process.env.DATABASE_URL = dbUrl;
  process.env.PRODUCTION_PLAN_TEST_DATABASE_URL ||= dbUrl;
  process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
  process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
  process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";
  process.env.STRIPE_USE_TEST_CLOCK = "false";
}

export async function loadProductionPlans() {
  assertProductionPlanTestEnvironment();
  const [
    db,
    stripeModule,
    plansServiceModule,
    onboardingModule,
    appConfigModule,
    subscriptionServiceModule,
    webhookModule,
  ] = await Promise.all([
    import("../../../src/config/database.js"),
    import("../../../src/modules/subscription/client/payment-providers/stripe/stripe.client.js"),
    import("../../../src/modules/subscription/service/plans.service.js"),
    import("../../../src/modules/subscription/service/onboarding.service.js"),
    import("../../../src/modules/subscription/repo/app-config.repo.js"),
    import("../../../src/modules/subscription/service/subscription.service.js"),
    import("../../../src/modules/subscription/service/stripe-webhook.service.js"),
  ]);

  return {
    prisma: db.prisma,
    stripeService: stripeModule.stripeService,
    stripe: stripeModule.stripeService.stripe,
    createPlansService: plansServiceModule.createPlansService,
    updatePlansService: plansServiceModule.updatePlansService,
    getPlans: plansServiceModule.getPlans,
    getManagedStandardPlans: plansServiceModule.getManagedStandardPlans,
    onBoardingService: onboardingModule.onBoardingService,
    getAppConfig: appConfigModule.getAppConfig,
    checkoutService: subscriptionServiceModule.checkoutService,
    webhookService: webhookModule.webhookService,
  };
}

export async function replaceStripeProductConfig(productId: string): Promise<string | null> {
  const { prisma } = await loadProductionPlans();
  const existing = await prisma.appConfig.findUnique({ where: { key: "STRIPE_PRODUCT_ID" } });
  await prisma.appConfig.upsert({
    where: { key: "STRIPE_PRODUCT_ID" },
    create: { key: "STRIPE_PRODUCT_ID", value: productId },
    update: { value: productId },
  });
  return existing?.value ?? null;
}

export async function restoreStripeProductConfig(previous: string | null): Promise<void> {
  const { prisma } = await loadProductionPlans();
  if (previous) {
    await prisma.appConfig.upsert({
      where: { key: "STRIPE_PRODUCT_ID" },
      create: { key: "STRIPE_PRODUCT_ID", value: previous },
      update: { value: previous },
    });
  } else {
    await prisma.appConfig.deleteMany({ where: { key: "STRIPE_PRODUCT_ID" } });
  }
}

export async function createStandardPlanFixture(options?: {
  basePriceUsd?: number;
  limitValue?: number;
  trialPeriodValue?: number;
  planNamePrefix?: string;
  active?: boolean;
}): Promise<StandardPlanFixture> {
  const { prisma, stripe, createPlansService } = await loadProductionPlans();
  const run = randomUUID().slice(0, 8);
  const basePriceUsd = options?.basePriceUsd ?? 20;
  const limitValue = options?.limitValue ?? 250;

  const product = await stripe.products.create({
    name: `CEOPRO Production Plan Verification ${run}`,
    metadata: { ceoproTestRun: run, purpose: "production-plan-verification" },
  });
  const previousStripeProductId = await replaceStripeProductConfig(product.id);

  const tenant = await prisma.company.create({
    data: {
      businessName: `Production Plan Tenant ${run}`,
      businessType: "test",
      countryCode: "JO",
      primaryCurrency: "USD",
    },
  });

  const email = `production-plan-${run}@example.test`;
  const user = await prisma.user.create({
    data: {
      email,
      passwordHash: "not-used-by-production-plan-e2e",
      fullName: `Production Plan ${run}`,
    },
  });

  const featureCode = `prod_plan_limit_${run}`;
  const feature = await prisma.feature.create({
    data: {
      code: featureCode,
      name: `Production Plan Limit ${run}`,
      name_ar: `Production Plan Limit ${run}`,
      type: "limit",
      unit: "count",
      unit_ar: "count",
      aggregationType: "sum",
      resetCycle: "billing_period",
    },
  });

  const planName = `${options?.planNamePrefix ?? "Production Fixture"} ${run}`;
  const created = await createPlansService({
    name: planName,
    name_ar: planName,
    tierLevel: 1,
    description: "Temporary production-shaped standard-plan verification fixture",
    description_ar: "Temporary production-shaped standard-plan verification fixture",
    price: basePriceUsd,
    currency: "USD",
    billingIntervalValue: 1,
    billingIntervalUnit: "month",
    trialPeriodValue: options?.trialPeriodValue ?? 0,
    isActive: options?.active ?? true,
    billingOptions: [
      {
        period: "monthly",
        months: 1,
        intervalUnit: "month",
        intervalCount: 1,
        discountPercent: 0,
      },
      {
        period: "yearly",
        months: 12,
        intervalUnit: "year",
        intervalCount: 1,
        discountPercent: 10,
      },
    ],
  } as any);

  assert.equal(created.success, true, `standard-plan creation must succeed: ${created.message ?? created.code ?? "unknown error"}`);
  const createdPlan = created.data;
  assert.ok(createdPlan?.id, "standard-plan creation must return a DB plan id");

  await prisma.planFeature.create({
    data: {
      plan_id: createdPlan.id,
      feature_id: feature.id,
      limit_value: limitValue,
      metadata: { test: true, source: "production-plan-verification" },
    },
  });

  const plan = await prisma.plan.findUniqueOrThrow({ where: { id: createdPlan.id } });
  const billingOptions = plan.billingOptions as Array<any>;
  const priceIds = billingOptions
    .map((option) => option?.stripePriceId)
    .filter((value): value is string => typeof value === "string" && value.length > 0);

  assert.equal(priceIds.length, 2, "fixture must create monthly + yearly Stripe Prices");

  return {
    run,
    tenantId: tenant.id,
    userId: user.userId,
    email,
    featureId: feature.id,
    featureCode,
    stripeProductId: product.id,
    previousStripeProductId,
    planId: plan.id,
    priceIds,
  };
}

export function makeProviderEvent<T extends Stripe.Event.Type>(args: {
  id?: string;
  type: T;
  object: any;
}): Stripe.Event {
  const now = Math.floor(Date.now() / 1000);
  return {
    id: args.id ?? `evt_prodplan_${randomUUID().replaceAll("-", "")}`,
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

export async function attachPaymentMethod(args: {
  run: string;
  tenantId: string;
}): Promise<{ customer: Stripe.Customer; paymentMethodId: string }> {
  const { stripe } = await loadProductionPlans();
  const customer = await stripe.customers.create({
    email: `prod-plan-sub-${args.run}@example.test`,
    metadata: { tenantId: args.tenantId, ceoproTestRun: args.run },
  });
  const paymentMethodId = process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa";
  const paymentMethod = await stripe.paymentMethods.attach(paymentMethodId, {
    customer: customer.id,
  });
  await stripe.customers.update(customer.id, {
    invoice_settings: { default_payment_method: paymentMethod.id },
  });
  return { customer, paymentMethodId: paymentMethod.id };
}

export async function cleanupStandardPlanFixture(
  fixture: StandardPlanFixture,
  extra?: {
    stripeCustomerIds?: string[];
    stripeSubscriptionIds?: string[];
    webhookEventIds?: string[];
    extraPlanIds?: string[];
    extraFeatureIds?: string[];
  },
): Promise<void> {
  const { prisma, stripe } = await loadProductionPlans();

  for (const subscriptionId of extra?.stripeSubscriptionIds ?? []) {
    try {
      const subscription = await stripe.subscriptions.retrieve(subscriptionId);
      if (subscription.status !== "canceled") await stripe.subscriptions.cancel(subscriptionId);
    } catch {}
  }

  for (const customerId of extra?.stripeCustomerIds ?? []) {
    try {
      await stripe.customers.del(customerId);
    } catch {}
  }

  if (extra?.webhookEventIds?.length) {
    await prisma.payment_providerWebhookEvent.deleteMany({
      where: { payment_providerEventId: { in: extra.webhookEventIds } },
    });
  }

  await prisma.platformNotificationOutbox.deleteMany({ where: { tenantId: fixture.tenantId } });
  await prisma.tenantNotificationOutbox.deleteMany({ where: { tenantId: fixture.tenantId } });

  const subscriptions = await prisma.subscription.findMany({
    where: { tenantId: fixture.tenantId },
    select: { id: true },
  });
  const subscriptionIds = subscriptions.map((row) => row.id);
  if (subscriptionIds.length) {
    await prisma.promoCodeRedemption.deleteMany({ where: { subscriptionId: { in: subscriptionIds } } });
    await prisma.paymentTransaction.deleteMany({ where: { subscriptionId: { in: subscriptionIds } } });
    await prisma.subscriptionUsage.deleteMany({ where: { subscription_id: { in: subscriptionIds } } });
    await prisma.subscription.deleteMany({ where: { id: { in: subscriptionIds } } });
  }

  const planIds = [fixture.planId, ...(extra?.extraPlanIds ?? [])];
  await prisma.promoCodePlan.deleteMany({ where: { planId: { in: planIds } } });
  await prisma.planFeature.deleteMany({ where: { plan_id: { in: planIds } } });
  await prisma.planPriceVersion.deleteMany({ where: { planId: { in: planIds } } });
  await prisma.plan.deleteMany({ where: { id: { in: planIds } } });

  const featureIds = [fixture.featureId, ...(extra?.extraFeatureIds ?? [])];
  await prisma.feature.deleteMany({ where: { id: { in: featureIds } } });
  await prisma.user.deleteMany({ where: { userId: fixture.userId } });
  await prisma.company.deleteMany({ where: { id: fixture.tenantId } });

  for (const priceId of fixture.priceIds) {
    try {
      await stripe.prices.update(priceId, { active: false });
    } catch {}
  }
  try {
    await stripe.products.update(fixture.stripeProductId, { active: false });
  } catch {}

  await restoreStripeProductConfig(fixture.previousStripeProductId);
}

export async function disconnectProductionPlanDb(): Promise<void> {
  const { prisma } = await loadProductionPlans();
  await prisma.$disconnect();
}
