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
} from "./_subscription-lifecycle-helpers.js";

assertLifecycleTestEnvironment();

test("23.01 cancel-at-period-end, undo cancellation, and final cancellation stay provider-authoritative", async () => {
  const fixture = await createLifecycleFixture();
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const {
      prisma,
      stripe,
      webhookService,
      cancelSubscriptionService,
      undoCancelSubscriptionService,
      getRemainingUsage,
      subscriptionRepo,
    } = await loadLifecycle();

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
    });
    subscriptionId = subscription.id;

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    assert.equal((await cancelSubscriptionService(fixture.tenantId)).success, true);
    const providerCancelled = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(providerCancelled.cancel_at_period_end, true);

    let local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(
      local.cancelAtPeriodEnd,
      false,
      "service should wait for provider webhook/sync before changing local cancellation state",
    );

    const cancelUpdateEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: providerCancelled,
    });
    eventIds.push(cancelUpdateEvent.id);
    assert.equal((await webhookService(cancelUpdateEvent)).success, true);

    local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.cancelAtPeriodEnd, true);
    assert.equal(local.status, "active");
    assert.ok(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode));

    assert.equal((await undoCancelSubscriptionService(fixture.tenantId)).success, true);
    const providerRestored = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(providerRestored.cancel_at_period_end, false);

    const undoEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: providerRestored,
    });
    eventIds.push(undoEvent.id);
    assert.equal((await webhookService(undoEvent)).success, true);

    local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.cancelAtPeriodEnd, false);

    const deleted = await stripe.subscriptions.cancel(subscription.id);
    const deletedEvent = makeLifecycleEvent({
      type: "customer.subscription.deleted",
      object: deleted,
    });
    eventIds.push(deletedEvent.id);
    assert.equal((await webhookService(deletedEvent)).success, true);

    local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.status, "cancelled");
    assert.equal(local.cancelAtPeriodEnd, false);
    assert.equal(await subscriptionRepo.getCurrentSubscriptionByTenant(fixture.tenantId), null);
    assert.equal(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode), null);
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});
