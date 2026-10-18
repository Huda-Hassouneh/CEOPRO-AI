import test from "node:test";
import assert from "node:assert/strict";
import {
  assertStripeTestEnvironment,
  cleanupFixture,
  createBaseAcceptedPlan,
  createStripeCustomerWithPaymentMethod,
  disconnectDb,
  loadCeopro,
  makeEvent,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("14.01 real Stripe TEST subscription synchronizes active access and usage allocation", async () => {
  const fixture = await createBaseAcceptedPlan({ finalPriceJod: 15, limitValue: 75 });
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  let eventId: string | undefined;
  try {
    const { prisma, stripe, webhookService } = await loadCeopro();
    const { customer, paymentMethodId } = await createStripeCustomerWithPaymentMethod({
      run: fixture.run,
      tenantId: fixture.tenantId,
    });
    customerId = customer.id;

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.stripePriceId }],
      default_payment_method: paymentMethodId,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "error_if_incomplete",
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "active");

    const event = makeEvent({ type: "customer.subscription.created", object: subscription });
    eventId = event.id;
    const first = await webhookService(event);
    assert.equal(first.success, true);
    assert.equal(first.data?.duplicate, false);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.tenantId, fixture.tenantId);
    assert.equal(local.planId, fixture.planId);
    assert.equal(local.status, "active");
    assert.equal(local.paymentProviderPriceId, fixture.stripePriceId);

    const usages = await prisma.subscriptionUsage.findMany({
      where: { subscription_id: local.id, feature_id: fixture.featureId },
    });
    assert.equal(usages.length, 1, "active subscription must get one metered allocation");
    assert.equal(usages[0].current_usage, 0);

    const duplicate = await webhookService(event);
    assert.equal(duplicate.success, true);
    assert.equal(duplicate.data?.duplicate, true);
    assert.equal(
      await prisma.subscription.count({
        where: { paymentProviderSubscriptionId: subscription.id },
      }),
      1,
    );
  } finally {
    if (eventId) {
      const { prisma } = await loadCeopro();
      await prisma.payment_providerWebhookEvent.deleteMany({ where: { payment_providerEventId: eventId } });
    }
    await cleanupFixture({
      ...fixture,
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
    });
    await disconnectDb();
  }
});
