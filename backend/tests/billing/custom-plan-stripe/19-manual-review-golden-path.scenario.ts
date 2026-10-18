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

test("19.01 manual-review quote calculates, approves, sends, accepts, checks out and synchronizes", async () => {
  const run = randomUUID().slice(0, 8);
  const resources: any = {
    run,
    stripeCustomerIds: [],
    stripeSubscriptionIds: [],
    extraCompanyIds: [],
    extraUserIds: [],
  };
  const eventIds: string[] = [];
  try {
    const { prisma, stripe, checkoutService, webhookService } = await loadCeopro();
    const customPlan = await import("../../../src/modules/subscription/service/custom-plan.service.js");

    const product = await stripe.products.create({
      name: `CEOPRO manual golden ${run}`,
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
        businessName: `Manual Golden ${run}`,
        businessType: "test",
        countryCode: "JO",
        primaryCurrency: "JOD",
      },
    });
    resources.tenantId = tenant.id;

    const platform = await prisma.company.create({
      data: {
        businessName: `CEOPRO Platform Test ${run}`,
        businessType: "platform",
        countryCode: "JO",
        primaryCurrency: "JOD",
      },
    });
    resources.extraCompanyIds.push(platform.id);

    await prisma.systemRole.upsert({
      where: { roleKey: "owner" },
      create: { roleKey: "owner", roleName: "Owner", permissions: { all: true } },
      update: { permissions: { all: true } },
    });
    const actor = await prisma.user.create({
      data: {
        email: `platform-${run}@example.test`,
        passwordHash: "not-used-in-e2e",
        fullName: "Stripe E2E Platform Actor",
      },
    });
    resources.extraUserIds.push(actor.userId);
    await prisma.tenantUser.create({
      data: {
        tenantId: platform.id,
        userId: actor.userId,
        roleKey: "owner",
        platformStatus: "active",
      },
    });

    const feature = await prisma.feature.create({
      data: {
        code: `manual_cp_${run}`,
        name: `Manual feature ${run}`,
        name_ar: `Manual feature ${run}`,
        type: "limit",
        unit: "count",
        unit_ar: "count",
        aggregationType: "sum",
        resetCycle: "billing_period",
      },
    });
    resources.featureId = feature.id;

    const created = await customPlan.createCustomPlanQuote(tenant.id, actor.userId, {
      name: `Manual ${run}`,
      name_ar: `Manual ${run}`,
      currency: "JOD",
      billingIntervalValue: 1,
      billingIntervalUnit: "month",
      trialPeriodValue: 0,
      billingOptions: [{ period: "monthly", months: 1, discountPercent: 0 }],
      features: [{ featureId: feature.id, limitValue: 250, estimatedUsage: 250 }],
      monthlyInfrastructureCost: 0,
      activePayingTenants: 1,
      estimatedOtherCost: 0,
      targetGrossMargin: 0.35,
      maxVendorCostRevenueRatio: 0.2,
      fxRate: 0.709,
      fxSourceCurrency: "USD",
      fxTargetCurrency: "JOD",
      fxSource: "Stripe E2E",
      fxRateAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    });
    assert.equal(created.success, true);
    resources.quoteId = created.data.id;

    const calculated = await customPlan.calculateCustomPlanQuote(tenant.id, created.data.id);
    assert.equal(calculated.success, true);
    assert.equal(calculated.data.status, "calculated");

    const finalPrice = Math.max(Number(calculated.data.minimumSafePrice), 30);
    const approved = await customPlan.approveCustomPlanQuote(
      tenant.id,
      created.data.id,
      actor.userId,
      { finalPrice },
      false,
    );
    assert.equal(approved.success, true);

    const sent = await customPlan.sendCustomPlanQuote(tenant.id, created.data.id, {
      tenantId: platform.id,
      userId: actor.userId,
    });
    assert.equal(sent.success, true);
    assert.equal(sent.data.status, "sent");

    const accepted = await customPlan.acceptCustomPlanQuote(tenant.id, created.data.id);
    assert.equal(accepted.success, true);
    resources.planId = accepted.data.id;

    const plan = await prisma.plan.findUniqueOrThrow({
      where: { id: accepted.data.id },
      include: { planFeatures: true },
    });
    assert.equal(plan.planFeatures[0].limit_value, 250);

    const checkout = await checkoutService(
      { planId: plan.id, billing_period: "monthly", payment_method: "stripe" },
      { id: randomUUID(), email: `manual-${run}@example.test`, tenant_id: tenant.id },
    );
    assert.equal(checkout.success, true);
    const sessionId = new URL(checkout.data!.checkoutUrl).pathname.split("/").filter(Boolean).at(-1)!;
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    const customerId = typeof session.customer === "string" ? session.customer : session.customer?.id;
    assert.ok(customerId);
    resources.stripeCustomerIds.push(customerId);

    const pm = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: customerId! },
    );
    await stripe.customers.update(customerId!, {
      invoice_settings: { default_payment_method: pm.id },
    });

    const stripePriceId = (plan.billingOptions as Array<any>)[0].stripePriceId;
    const subscription = await stripe.subscriptions.create({
      customer: customerId!,
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
