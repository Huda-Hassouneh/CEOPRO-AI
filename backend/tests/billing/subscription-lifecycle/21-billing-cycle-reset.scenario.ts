import test from "node:test";
import assert from "node:assert/strict";
import {
  assertLifecycleTestEnvironment,
  cleanupLifecycleFixture,
  createCustomerWithPaymentMethod,
  createLifecycleFixture,
  disconnectLifecycleDb,
  loadLifecycle,
  makeLifecycleEvent,
  waitForLifecycle,
} from "./_subscription-lifecycle-helpers.js";

assertLifecycleTestEnvironment();

test("21.01 renewal creates one new billing-period allocation, preserves lifetime usage, and is idempotent", async () => {
  const fixture = await createLifecycleFixture();
  let clockId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const { prisma, stripe, webhookService } = await loadLifecycle();
    const clock = await stripe.testHelpers.testClocks.create({
      name: `Lifecycle reset ${fixture.run}`,
      frozen_time: Math.floor(Date.now() / 1000) - 60,
    });
    clockId = clock.id;

    const { customer, paymentMethodId } = await createCustomerWithPaymentMethod({
      run: fixture.run,
      tenantId: fixture.tenantId,
      testClockId: clock.id,
    });
    customerId = customer.id;

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.plans[0].stripePriceId }],
      default_payment_method: paymentMethodId,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "error_if_incomplete",
    });
    subscriptionId = subscription.id;

    const initialEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(initialEvent.id);
    assert.equal((await webhookService(initialEvent)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });

    await prisma.subscriptionUsage.updateMany({
      where: {
        subscription_id: local.id,
        feature_id: fixture.billingFeatureId,
      },
      data: { current_usage: 37 },
    });
    await prisma.subscriptionUsage.updateMany({
      where: {
        subscription_id: local.id,
        feature_id: fixture.lifetimeFeatureId,
      },
      data: { current_usage: 4 },
    });

    const initialStart = subscription.items.data[0].current_period_start;
    const initialEnd = subscription.items.data[0].current_period_end;

    await stripe.testHelpers.testClocks.advance(clock.id, {
      frozen_time: initialEnd + 60 * 60,
    });
    await waitForLifecycle(
      "Stripe Test Clock renewal",
      () => stripe.testHelpers.testClocks.retrieve(clock.id),
      (value) => value.status === "ready",
    );

    const renewed = await waitForLifecycle(
      "subscription period to advance",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.items.data[0].current_period_start > initialStart,
    );

    const renewalEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: renewed,
    });
    eventIds.push(renewalEvent.id);
    const first = await webhookService(renewalEvent);
    const duplicate = await webhookService(renewalEvent);
    assert.equal(first.success, true);
    assert.equal(duplicate.success, true);
    assert.equal(duplicate.data?.duplicate, true);

    const billingAllocations = await prisma.subscriptionUsage.findMany({
      where: {
        subscription_id: local.id,
        feature_id: fixture.billingFeatureId,
      },
      orderBy: { period_start: "asc" },
    });
    assert.equal(billingAllocations.length, 2);
    assert.equal(billingAllocations[0].current_usage, 37, "old usage must remain historical");
    assert.equal(billingAllocations[1].current_usage, 0, "new billing period must start at zero");

    const lifetimeAllocations = await prisma.subscriptionUsage.findMany({
      where: {
        subscription_id: local.id,
        feature_id: fixture.lifetimeFeatureId,
      },
    });
    assert.equal(lifetimeAllocations.length, 1, "lifetime features must not reset each billing cycle");
    assert.equal(lifetimeAllocations[0].current_usage, 4);
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      stripeTestClockIds: clockId ? [clockId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});
