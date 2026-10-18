import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import {
  assertStripeTestEnvironment,
  cleanupFixture,
  disconnectDb,
  loadCeopro,
  makeEvent,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("18.01 automatic configuration reaches Stripe Checkout, custom plan, subscription and entitlement", async () => {
  const run = randomUUID().slice(0, 8);
  const resources: any = { run, stripeCustomerIds: [], stripeSubscriptionIds: [] };
  const eventIds: string[] = [];
  try {
    const { prisma, stripe, webhookService } = await loadCeopro();
    const { checkoutCustomPlanConfiguration } = await import(
      "../../../src/modules/subscription/service/custom-plan-configurator.service.js"
    );

    const product = await stripe.products.create({
      name: `CEOPRO automatic golden ${run}`,
      metadata: { ceoproTestRun: run },
    });
    resources.stripeProductId = product.id;
    await prisma.appConfig.upsert({
      where: { key: "STRIPE_PRODUCT_ID" },
      create: { key: "STRIPE_PRODUCT_ID", value: product.id },
      update: { value: product.id },
    });

    const tenant = await prisma.company.create({
      data: {
        businessName: `Automatic Golden ${run}`,
        businessType: "test",
        countryCode: "JO",
        primaryCurrency: "JOD",
      },
    });
    resources.tenantId = tenant.id;

    const feature = await prisma.feature.create({
      data: {
        code: `auto_cp_${run}`,
        name: `Automatic feature ${run}`,
        name_ar: `Automatic feature ${run}`,
        type: "limit",
        unit: "count",
        unit_ar: "count",
        aggregationType: "sum",
        resetCycle: "billing_period",
      },
    });
    resources.featureId = feature.id;

    const requestId = randomUUID();
    resources.quoteId = requestId;
    const checkout = await checkoutCustomPlanConfiguration(
      tenant.id,
      { id: randomUUID(), email: `auto-${run}@example.test` },
      {
        requestId,
        paymentMethod: "stripe",
        billingPeriod: "monthly",
        features: [{ featureId: feature.id, limitValue: 123 }],
      },
    );

    assert.equal(checkout.success, true);
    assert.equal(checkout.data?.manualReviewRequired, false);
    assert.ok(checkout.data?.checkoutUrl);
    resources.planId = checkout.data.planId;

    const quote = await prisma.customPlanQuote.findUniqueOrThrow({ where: { id: requestId } });
    assert.equal(quote.status, "accepted");
    assert.ok(quote.pricingSnapshot);

    const plan = await prisma.plan.findUniqueOrThrow({
      where: { id: checkout.data.planId },
      include: { planFeatures: true },
    });
    assert.equal(plan.planType, "custom");
    assert.equal(plan.tenantId, tenant.id);
    assert.equal(plan.planFeatures[0].limit_value, 123);

    const sessionId = new URL(checkout.data.checkoutUrl).pathname.split("/").filter(Boolean).at(-1)!;
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    const checkoutCustomerId = typeof session.customer === "string" ? session.customer : session.customer?.id;
    assert.ok(checkoutCustomerId);
    resources.stripeCustomerIds.push(checkoutCustomerId);

    const pm = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: checkoutCustomerId! },
    );
    await stripe.customers.update(checkoutCustomerId!, {
      invoice_settings: { default_payment_method: pm.id },
    });

    const stripePriceId = (plan.billingOptions as Array<any>)[0].stripePriceId;
    const subscription = await stripe.subscriptions.create({
      customer: checkoutCustomerId!,
      items: [{ price: stripePriceId }],
      default_payment_method: pm.id,
      metadata: { tenantId: tenant.id, ceoproTestRun: run },
      payment_behavior: "error_if_incomplete",
    });
    resources.stripeSubscriptionIds.push(subscription.id);

    const event = makeEvent({ type: "customer.subscription.created", object: subscription });
    eventIds.push(event.id);
    assert.equal((await webhookService(event)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.status, "active");
    assert.equal(local.planId, plan.id);
    assert.equal(
      await prisma.subscriptionUsage.count({
        where: { subscription_id: local.id, feature_id: feature.id },
      }),
      1,
    );
  } finally {
    const { prisma } = await loadCeopro();
    if (eventIds.length) {
      await prisma.payment_providerWebhookEvent.deleteMany({
        where: { payment_providerEventId: { in: eventIds } },
      });
    }
    await cleanupFixture(resources);
    await disconnectDb();
  }
});
