import test from "node:test";
import assert from "node:assert/strict";
import {
  assertProductionPlanTestEnvironment,
  attachPaymentMethod,
  cleanupStandardPlanFixture,
  createStandardPlanFixture,
  disconnectProductionPlanDb,
  loadProductionPlans,
  makeProviderEvent,
} from "./_production-plan-helpers.js";

assertProductionPlanTestEnvironment();

test("32.01 successful standard-plan Stripe subscription synchronizes the correct plan and feature allocation", async () => {
  const fixture = await createStandardPlanFixture({ basePriceUsd: 25, limitValue: 777 });
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  let eventId: string | undefined;
  try {
    const { prisma, stripe, webhookService } = await loadProductionPlans();
    const { customer, paymentMethodId } = await attachPaymentMethod({
      run: fixture.run,
      tenantId: fixture.tenantId,
    });
    customerId = customer.id;

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.priceIds[0] }],
      default_payment_method: paymentMethodId,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "error_if_incomplete",
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "active");

    const event = makeProviderEvent({ type: "customer.subscription.created", object: subscription });
    eventId = event.id;
    const handled = await webhookService(event);
    assert.equal(handled.success, true);
    assert.equal(handled.data?.duplicate, false);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.tenantId, fixture.tenantId);
    assert.equal(local.planId, fixture.planId);
    assert.equal(local.paymentProviderPriceId, fixture.priceIds[0]);
    assert.equal(local.status, "active");

    const allocations = await prisma.subscriptionUsage.findMany({
      where: { subscription_id: local.id, feature_id: fixture.featureId },
    });
    assert.equal(allocations.length, 1);
    assert.equal(allocations[0].current_usage, 0);
  } finally {
    await cleanupStandardPlanFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      webhookEventIds: eventId ? [eventId] : [],
    });
    await disconnectProductionPlanDb();
  }
});
