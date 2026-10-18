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

test("22.01 trialing grants access and transitions to active after successful trial-end charge", async () => {
  const fixture = await createLifecycleFixture();
  let clockId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const { prisma, stripe, webhookService, getRemainingUsage } = await loadLifecycle();
    const clock = await stripe.testHelpers.testClocks.create({
      name: `Lifecycle paid trial ${fixture.run}`,
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
      trial_period_days: 1,
      trial_settings: { end_behavior: { missing_payment_method: "cancel" } },
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "trialing");
    assert.ok(subscription.trial_end);

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    const localTrial = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(localTrial.status, "trialing");
    assert.ok(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode));

    await stripe.testHelpers.testClocks.advance(clock.id, {
      frozen_time: subscription.trial_end! + 60 * 60,
    });
    await waitForLifecycle(
      "paid trial clock",
      () => stripe.testHelpers.testClocks.retrieve(clock.id),
      (value) => value.status === "ready",
    );

    const active = await waitForLifecycle(
      "trial subscription to become active",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.status === "active",
    );

    const updatedEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: active,
    });
    eventIds.push(updatedEvent.id);
    assert.equal((await webhookService(updatedEvent)).success, true);

    const localActive = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(localActive.status, "active");
    assert.ok(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode));
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

test("22.02 missing payment method can move a direct trial to paused and removes access", async () => {
  const fixture = await createLifecycleFixture();
  let clockId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const { prisma, stripe, webhookService, getRemainingUsage } = await loadLifecycle();
    const clock = await stripe.testHelpers.testClocks.create({
      name: `Lifecycle paused trial ${fixture.run}`,
      frozen_time: Math.floor(Date.now() / 1000) - 60,
    });
    clockId = clock.id;

    const customer = await stripe.customers.create({
      email: `paused-${fixture.run}@example.test`,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      test_clock: clock.id,
    });
    customerId = customer.id;

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.plans[0].stripePriceId }],
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      trial_period_days: 1,
      trial_settings: { end_behavior: { missing_payment_method: "pause" } },
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "trialing");
    assert.ok(subscription.trial_end);

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);
    assert.ok(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode));

    await stripe.testHelpers.testClocks.advance(clock.id, {
      frozen_time: subscription.trial_end! + 60 * 60,
    });
    await waitForLifecycle(
      "paused trial clock",
      () => stripe.testHelpers.testClocks.retrieve(clock.id),
      (value) => value.status === "ready",
    );

    const paused = await waitForLifecycle(
      "trial subscription to become paused",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.status === "paused",
    );

    const pausedEvent = makeLifecycleEvent({
      type: "customer.subscription.paused",
      object: paused,
    });
    eventIds.push(pausedEvent.id);
    assert.equal((await webhookService(pausedEvent)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.status, "paused");
    assert.equal(
      await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode),
      null,
      "paused subscription must not grant feature access",
    );
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
