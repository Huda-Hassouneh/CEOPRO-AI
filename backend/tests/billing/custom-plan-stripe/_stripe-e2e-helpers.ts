import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type Stripe from "stripe";

export const TEST_WEBHOOK_SECRET =
  process.env.STRIPE_E2E_WEBHOOK_SECRET?.trim() || "whsec_ceopro_local_e2e_secret";

export function assertStripeTestEnvironment(): void {
  const dbUrl = process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim();
  const stripeKey = process.env.STRIPE_SECRET_KEY?.trim();

  assert.ok(
    dbUrl,
    "CUSTOM_PLAN_TEST_DATABASE_URL is required and must point at a disposable migrated database.",
  );
  assert.ok(stripeKey, "STRIPE_SECRET_KEY is required for Stripe E2E tests.");
  assert.ok(
    stripeKey.startsWith("sk_test_"),
    "Refusing to run Stripe E2E tests unless STRIPE_SECRET_KEY starts with sk_test_.",
  );

  process.env.DATABASE_URL = dbUrl;
  process.env.STRIPE_SECRET_WEBHOOK = TEST_WEBHOOK_SECRET;
  process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
  process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
  process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";
  process.env.STRIPE_USE_TEST_CLOCK = "false";
}

export type StripeDbFixture = {
  run: string;
  tenantId: string;
  featureId: string;
  featureCode: string;
  quoteId: string;
  planId: string;
  stripeProductId: string;
  stripePriceId: string;
  finalPriceJod: number;
};

export async function loadCeopro() {
  assertStripeTestEnvironment();
  const [db, stripeModule, customPlanRepoModule, customPlanServiceModule, subscriptionServiceModule, webhookServiceModule] =
    await Promise.all([
      import("../../../src/config/database.js"),
      import("../../../src/modules/subscription/client/payment-providers/stripe/stripe.client.js"),
      import("../../../src/modules/subscription/repo/custom-plan.repo.js"),
      import("../../../src/modules/subscription/service/custom-plan.service.js"),
      import("../../../src/modules/subscription/service/subscription.service.js"),
      import("../../../src/modules/subscription/service/stripe-webhook.service.js"),
    ]);

  return {
    prisma: db.prisma,
    stripeService: stripeModule.stripeService,
    stripe: stripeModule.stripeService.stripe,
    customPlanRepository: customPlanRepoModule.default,
    acceptCustomPlanQuote: customPlanServiceModule.acceptCustomPlanQuote,
    checkoutService: subscriptionServiceModule.checkoutService,
    webhookService: webhookServiceModule.webhookService,
  };
}

export async function createBaseAcceptedPlan(options?: {
  finalPriceJod?: number;
  featureType?: "limit" | "boolean";
  limitValue?: number | null;
  trialPeriodValue?: number;
  billingOptions?: Array<{ period: string; months: number; discountPercent: number }>;
}): Promise<StripeDbFixture> {
  const {
    prisma,
    stripe,
    customPlanRepository,
    acceptCustomPlanQuote,
  } = await loadCeopro();

  const run = randomUUID().slice(0, 8);
  const finalPriceJod = options?.finalPriceJod ?? 10;
  const featureType = options?.featureType ?? "limit";
  const limitValue = featureType === "limit" ? (options?.limitValue ?? 25) : null;
  const billingOptions = options?.billingOptions ?? [
    { period: "monthly", months: 1, discountPercent: 0 },
  ];

  const product = await stripe.products.create({
    name: `CEOPRO Custom Plan E2E ${run}`,
    metadata: { ceoproTestRun: run, purpose: "custom-plan-e2e" },
  });

  await prisma.appConfig.upsert({
    where: { key: "STRIPE_PRODUCT_ID" },
    create: { key: "STRIPE_PRODUCT_ID", value: product.id },
    update: { value: product.id },
  });

  const tenant = await prisma.company.create({
    data: {
      businessName: `Stripe CP Test ${run}`,
      businessType: "test",
      countryCode: "JO",
      primaryCurrency: "JOD",
    },
  });

  const featureCode = `stripe_cp_${run}`;
  const feature = await prisma.feature.create({
    data: {
      code: featureCode,
      name: `Stripe Custom Plan ${run}`,
      name_ar: `Stripe Custom Plan ${run}`,
      type: featureType,
      unit: featureType === "limit" ? "count" : null,
      unit_ar: featureType === "limit" ? "count" : null,
      aggregationType: "sum",
      resetCycle: "billing_period",
    },
  });

  const quote = await customPlanRepository.createQuote({
    tenantId: tenant.id,
    data: {
      name: `Stripe Test ${run}`,
      nameAr: `Stripe Test ${run}`,
      description: "Automated Stripe custom-plan integration test",
      descriptionAr: "Automated Stripe custom-plan integration test",
      status: "approved",
      currency: "JOD",
      billingIntervalValue: 1,
      billingIntervalUnit: "month",
      trialPeriodValue: options?.trialPeriodValue ?? 0,
      billingOptions,
      estimatedVendorCost: 0,
      estimatedInfrastructureCost: 0,
      estimatedOtherCost: 0,
      estimatedTotalCost: 0,
      targetGrossMargin: 0.35,
      maxVendorCostRevenueRatio: 0.2,
      grossMarginFloor: 0,
      vendorCostRatioFloor: 0,
      minimumSafePrice: 0,
      finalPrice: finalPriceJod,
      fxRate: 0.709,
      fxSourceCurrency: "USD",
      fxTargetCurrency: "JOD",
      fxSource: "Stripe E2E test fixture",
      fxRateAt: new Date(),
      pricingInputs: { test: true },
      pricingSnapshot: { test: true },
      expiresAt: new Date(Date.now() + 60 * 60 * 1000),
    },
    features: [
      {
        featureId: feature.id,
        limitValue,
        estimatedUsage: featureType === "limit" ? Number(limitValue ?? 0) : 0,
        metadata: { source: "stripe-e2e" },
      },
    ],
  });

  const accepted = await acceptCustomPlanQuote(tenant.id, quote.id);
  assert.equal(accepted.success, true, "quote acceptance must succeed");
  assert.ok(accepted.data?.id, "accepted quote must produce a plan");

  const plan = await prisma.plan.findUniqueOrThrow({
    where: { id: accepted.data.id },
    include: { planFeatures: { include: { feature: true } } },
  });
  const optionsJson = plan.billingOptions as Array<any>;
  const stripePriceId = optionsJson[0]?.stripePriceId;
  assert.ok(stripePriceId, "accepted custom plan must contain a Stripe Price ID");

  return {
    run,
    tenantId: tenant.id,
    featureId: feature.id,
    featureCode,
    quoteId: quote.id,
    planId: plan.id,
    stripeProductId: product.id,
    stripePriceId,
    finalPriceJod,
  };
}

export async function createStripeCustomerWithPaymentMethod(args: {
  run: string;
  tenantId: string;
  paymentMethodId?: string;
  testClockId?: string;
}): Promise<{ customer: Stripe.Customer; paymentMethodId: string }> {
  const { stripe } = await loadCeopro();
  const paymentMethodId =
    args.paymentMethodId ?? process.env.STRIPE_E2E_VALID_PAYMENT_METHOD ?? "pm_card_visa";

  const customer = await stripe.customers.create({
    email: `ceopro-stripe-${args.run}@example.test`,
    name: `CEOPRO Stripe ${args.run}`,
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

export function makeEvent<T extends Stripe.Event.Type>(args: {
  id?: string;
  type: T;
  object: any;
}): Stripe.Event {
  const now = Math.floor(Date.now() / 1000);
  return {
    id: args.id ?? `evt_ceopro_${randomUUID().replaceAll("-", "")}`,
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

export async function waitFor<T>(
  label: string,
  load: () => Promise<T>,
  predicate: (value: T) => boolean,
  timeoutMs = 90_000,
  intervalMs = 1_500,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: T;
  while (true) {
    last = await load();
    if (predicate(last)) return last;
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for ${label}`);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export async function cleanupFixture(
  fixture: Partial<StripeDbFixture> & {
    stripeCustomerIds?: string[];
    stripeSubscriptionIds?: string[];
    stripeCouponIds?: string[];
    stripeTestClockIds?: string[];
    promoCodeIds?: string[];
    extraCompanyIds?: string[];
    extraUserIds?: string[];
  },
): Promise<void> {
  const { prisma, stripe } = await loadCeopro();

  for (const subscriptionId of fixture.stripeSubscriptionIds ?? []) {
    try {
      const sub = await stripe.subscriptions.retrieve(subscriptionId);
      if (sub.status !== "canceled") await stripe.subscriptions.cancel(subscriptionId);
    } catch {}
  }

  for (const customerId of fixture.stripeCustomerIds ?? []) {
    try {
      await stripe.customers.del(customerId);
    } catch {}
  }

  for (const couponId of fixture.stripeCouponIds ?? []) {
    try {
      await stripe.coupons.del(couponId);
    } catch {}
  }

  for (const clockId of fixture.stripeTestClockIds ?? []) {
    try {
      const api = stripe.testHelpers.testClocks as any;
      if (typeof api.del === "function") await api.del(clockId);
    } catch {}
  }

  const tenantIds = [fixture.tenantId, ...(fixture.extraCompanyIds ?? [])].filter(
    (value): value is string => Boolean(value),
  );

  if (tenantIds.length) {
    const subscriptions = await prisma.subscription.findMany({
      where: { tenantId: { in: tenantIds } },
      select: { id: true },
    });
    const subscriptionIds = subscriptions.map((row) => row.id);
    if (subscriptionIds.length) {
      await prisma.promoCodeRedemption.deleteMany({ where: { subscriptionId: { in: subscriptionIds } } });
      await prisma.paymentTransaction.deleteMany({ where: { subscriptionId: { in: subscriptionIds } } });
      await prisma.subscriptionUsage.deleteMany({ where: { subscription_id: { in: subscriptionIds } } });
      await prisma.subscription.deleteMany({ where: { id: { in: subscriptionIds } } });
    }
    await prisma.platformNotificationOutbox.deleteMany({ where: { tenantId: { in: tenantIds } } });
    await prisma.tenantNotificationOutbox.deleteMany({ where: { tenantId: { in: tenantIds } } });
  }

  for (const promoCodeId of fixture.promoCodeIds ?? []) {
    await prisma.promoCodePlan.deleteMany({ where: { promoCodeId } });
    await prisma.promoCodeRedemption.deleteMany({ where: { promoCodeId } });
    await prisma.promoCode.deleteMany({ where: { id: promoCodeId } });
  }

  if (fixture.planId) {
    await prisma.planFeature.deleteMany({ where: { plan_id: fixture.planId } });
    await prisma.planPriceVersion.deleteMany({ where: { planId: fixture.planId } });
    await prisma.plan.deleteMany({ where: { id: fixture.planId } });
  }
  if (fixture.quoteId) {
    await prisma.customPlanQuoteFeature.deleteMany({ where: { quoteId: fixture.quoteId } });
    await prisma.customPlanQuote.deleteMany({ where: { id: fixture.quoteId } });
  }
  if (fixture.featureId) {
    await prisma.feature.deleteMany({ where: { id: fixture.featureId } });
  }

  if (fixture.extraUserIds?.length) {
    await prisma.tenantUser.deleteMany({ where: { userId: { in: fixture.extraUserIds } } });
    await prisma.user.deleteMany({ where: { userId: { in: fixture.extraUserIds } } });
  }
  if (tenantIds.length) {
    await prisma.tenantUser.deleteMany({ where: { tenantId: { in: tenantIds } } });
    await prisma.company.deleteMany({ where: { id: { in: tenantIds } } });
  }

  if (fixture.stripeProductId) {
    try {
      const prices = await stripe.prices.list({ product: fixture.stripeProductId, limit: 100 });
      for (const price of prices.data) {
        if (price.active) await stripe.prices.update(price.id, { active: false });
      }
      await stripe.products.update(fixture.stripeProductId, { active: false });
    } catch {}
  }

  try {
    const current = await prisma.appConfig.findUnique({ where: { key: "STRIPE_PRODUCT_ID" } });
    if (current?.value === fixture.stripeProductId) {
      await prisma.appConfig.delete({ where: { key: "STRIPE_PRODUCT_ID" } });
    }
  } catch {}
}

export async function disconnectDb(): Promise<void> {
  const { prisma } = await loadCeopro();
  await prisma.$disconnect();
}
