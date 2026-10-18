import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import {
  assertLifecycleTestEnvironment,
  cleanupLifecycleFixture,
  createCustomerWithPaymentMethod,
  createLifecycleFixture,
  disconnectLifecycleDb,
  loadLifecycle,
  makeLifecycleEvent,
} from "./_subscription-lifecycle-helpers.js";

assertLifecycleTestEnvironment();

test("25.01 invoice webhook can arrive before subscription-created and still converges without duplicates", async () => {
  const fixture = await createLifecycleFixture();
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const { prisma, stripe, webhookService } = await loadLifecycle();
    const { customer, paymentMethodId } = await createCustomerWithPaymentMethod({
      run: fixture.run,
      tenantId: fixture.tenantId,
    });
    customerId = customer.id;

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.plans[0].stripePriceId }],
      default_payment_method: paymentMethodId,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "error_if_incomplete",
      expand: ["latest_invoice"],
    });
    subscriptionId = subscription.id;

    const invoiceId =
      typeof subscription.latest_invoice === "string"
        ? subscription.latest_invoice
        : subscription.latest_invoice?.id;
    assert.ok(invoiceId);
    const invoice = await stripe.invoices.retrieve(invoiceId!);

    const paymentEvent = makeLifecycleEvent({
      type: "invoice.payment_succeeded",
      object: invoice,
    });
    eventIds.push(paymentEvent.id);
    assert.equal((await webhookService(paymentEvent)).success, true);

    const afterInvoice = await prisma.subscription.findMany({
      where: { tenantId: fixture.tenantId },
    });
    assert.equal(afterInvoice.length, 1, "invoice-first delivery must create exactly one local subscription");

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);
    assert.equal(
      await prisma.subscription.count({ where: { tenantId: fixture.tenantId } }),
      1,
      "later subscription event must update rather than duplicate",
    );

    const duplicate = await webhookService(paymentEvent);
    assert.equal(duplicate.success, true);
    assert.equal(duplicate.data?.duplicate, true);
    assert.equal(
      await prisma.paymentTransaction.count({
        where: { subscriptionId: afterInvoice[0].id },
      }),
      1,
      "repeated provider event must not duplicate payment transaction",
    );
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});

test("25.02 failed webhook remains unprocessed and the same event succeeds after dependency repair", async () => {
  const { prisma, stripe, webhookService } = await loadLifecycle();
  const run = randomUUID().slice(0, 8);
  let tenantId: string | undefined;
  let featureId: string | undefined;
  let planId: string | undefined;
  let productId: string | undefined;
  let priceId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  let eventId: string | undefined;

  try {
    const tenant = await prisma.company.create({
      data: {
        businessName: `Webhook Retry ${run}`,
        businessType: "test",
        countryCode: "JO",
        primaryCurrency: "USD",
      },
    });
    tenantId = tenant.id;

    const product = await stripe.products.create({
      name: `Webhook Retry ${run}`,
      metadata: { ceoproTestRun: run },
    });
    productId = product.id;
    const price = await stripe.prices.create({
      product: product.id,
      currency: "usd",
      unit_amount: 900,
      recurring: { interval: "month" },
    });
    priceId = price.id;

    const customer = await stripe.customers.create({
      email: `retry-${run}@example.test`,
      metadata: { tenantId: tenant.id, ceoproTestRun: run },
    });
    customerId = customer.id;
    const paymentMethod = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: paymentMethod.id },
    });

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: price.id }],
      default_payment_method: paymentMethod.id,
      metadata: { tenantId: tenant.id, ceoproTestRun: run },
      payment_behavior: "error_if_incomplete",
    });
    subscriptionId = subscription.id;

    const event = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventId = event.id;

    const first = await webhookService(event);
    assert.equal(first.success, false, "missing local price mapping should make the handler fail");

    let audit = await prisma.payment_providerWebhookEvent.findUniqueOrThrow({
      where: { payment_providerEventId: event.id },
    });
    assert.equal(audit.processed, false, "failed webhook must remain retryable");
    assert.equal(
      await prisma.subscription.count({ where: { tenantId: tenant.id } }),
      0,
    );

    const feature = await prisma.feature.create({
      data: {
        code: `retry_feature_${run}`,
        name: `Retry Feature ${run}`,
        name_ar: `Retry Feature ${run}`,
        type: "limit",
        unit: "count",
        unit_ar: "count",
        aggregationType: "sum",
        resetCycle: "billing_period",
      },
    });
    featureId = feature.id;

    const plan = await prisma.plan.create({
      data: {
        name: `Retry ${run}`,
        name_ar: `Retry ${run}`,
        planType: "standard",
        price: 9,
        currency: "USD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month",
        trialPeriodValue: 0,
        paymentProviderProductId: product.id,
        billingOptions: [
          {
            period: "monthly",
            months: 1,
            discountPercent: 0,
            amount: 9,
            stripePriceId: price.id,
          },
        ],
        isActive: true,
      },
    });
    planId = plan.id;
    await prisma.planFeature.create({
      data: { plan_id: plan.id, feature_id: feature.id, limit_value: 25 },
    });
    await prisma.planPriceVersion.create({
      data: {
        planId: plan.id,
        stripePriceId: price.id,
        periodCode: "monthly",
        intervalUnit: "month",
        intervalCount: 1,
        amount: 9,
        currency: "USD",
      },
    });

    const second = await webhookService(event);
    assert.equal(second.success, true);
    assert.equal(second.data?.duplicate, false);

    audit = await prisma.payment_providerWebhookEvent.findUniqueOrThrow({
      where: { payment_providerEventId: event.id },
    });
    assert.equal(audit.processed, true);
    assert.equal(
      await prisma.subscription.count({ where: { tenantId: tenant.id } }),
      1,
    );
  } finally {
    if (subscriptionId) {
      try {
        const sub = await stripe.subscriptions.retrieve(subscriptionId);
        if (sub.status !== "canceled") await stripe.subscriptions.cancel(subscriptionId);
      } catch {}
    }
    if (customerId) {
      try { await stripe.customers.del(customerId); } catch {}
    }
    if (eventId) {
      await prisma.payment_providerWebhookEvent.deleteMany({
        where: { payment_providerEventId: eventId },
      });
    }
    if (tenantId) {
      const subs = await prisma.subscription.findMany({
        where: { tenantId },
        select: { id: true },
      });
      const ids = subs.map((row) => row.id);
      if (ids.length) {
        await prisma.paymentTransaction.deleteMany({ where: { subscriptionId: { in: ids } } });
        await prisma.subscriptionUsage.deleteMany({ where: { subscription_id: { in: ids } } });
        await prisma.subscription.deleteMany({ where: { id: { in: ids } } });
      }
      await prisma.platformNotificationOutbox.deleteMany({ where: { tenantId } });
      await prisma.tenantNotificationOutbox.deleteMany({ where: { tenantId } });
    }
    if (planId) {
      await prisma.planFeature.deleteMany({ where: { plan_id: planId } });
      await prisma.planPriceVersion.deleteMany({ where: { planId } });
      await prisma.plan.deleteMany({ where: { id: planId } });
    }
    if (featureId) await prisma.feature.deleteMany({ where: { id: featureId } });
    if (tenantId) await prisma.company.deleteMany({ where: { id: tenantId } });
    if (productId) {
      try {
        if (priceId) await stripe.prices.update(priceId, { active: false });
        await stripe.products.update(productId, { active: false });
      } catch {}
    }
    await disconnectLifecycleDb();
  }
});
