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

test("24.01 entitlement-only upgrade applies immediately during trial without resetting trial end", async () => {
  const fixture = await createLifecycleFixture({
    planLimits: [100, 200],
    priceAmountsUsd: [10, 20],
  });
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const { prisma, stripe, webhookService, changePlanService } = await loadLifecycle();
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
      trial_period_days: 7,
      trial_settings: { end_behavior: { missing_payment_method: "cancel" } },
    });
    subscriptionId = subscription.id;
    const originalTrialEnd = subscription.trial_end;
    assert.ok(originalTrialEnd);

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    const result = await changePlanService(
      fixture.plans[1].id,
      fixture.tenantId,
      "monthly",
    );
    assert.equal(result.success, true);
    assert.equal(result.data?.transitionType, "upgrade");
    assert.equal(result.data?.effectiveTiming, "immediate");
    assert.equal(result.data?.state, "applied");

    const provider = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(provider.status, "trialing");
    assert.equal(provider.trial_end, originalTrialEnd);
    assert.equal(provider.items.data[0].price.id, fixture.plans[1].stripePriceId);

    const updateEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: provider,
    });
    eventIds.push(updateEvent.id);
    assert.equal((await webhookService(updateEvent)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.planId, fixture.plans[1].id);
    assert.equal(local.status, "trialing");
    assert.equal(local.scheduledPlanId, null);
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});

test("24.02 entitlement downgrade schedules for period end and can be cancelled safely", async () => {
  const fixture = await createLifecycleFixture({
    planLimits: [100, 50],
    priceAmountsUsd: [20, 10],
  });
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const {
      prisma,
      stripe,
      webhookService,
      changePlanService,
      cancelScheduledPlanChangeService,
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

    const result = await changePlanService(
      fixture.plans[1].id,
      fixture.tenantId,
      "monthly",
    );
    assert.equal(result.success, true);
    assert.equal(result.data?.transitionType, "downgrade");
    assert.equal(result.data?.effectiveTiming, "period_end");
    assert.equal(result.data?.state, "scheduled");

    let local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.planId, fixture.plans[0].id, "current paid plan must remain active");
    assert.equal(local.scheduledPlanId, fixture.plans[1].id);
    assert.equal(local.scheduledBillingPeriod, "monthly");

    const providerScheduled = await stripe.subscriptions.retrieve(subscription.id);
    assert.ok(providerScheduled.schedule, "Stripe subscription schedule must exist");

    const cancelResult = await cancelScheduledPlanChangeService(fixture.tenantId);
    assert.equal(cancelResult.success, true);

    const providerReleased = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(providerReleased.schedule, null);

    local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.planId, fixture.plans[0].id);
    assert.equal(local.scheduledPlanId, null);
    assert.equal(local.scheduledBillingPeriod, null);
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});
