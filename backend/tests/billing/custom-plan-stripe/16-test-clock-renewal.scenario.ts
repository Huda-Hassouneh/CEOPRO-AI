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
  waitFor,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("16.01 Stripe Test Clock renewal advances billing period and creates exactly one new allocation", async () => {
  const fixture = await createBaseAcceptedPlan({ finalPriceJod: 12, limitValue: 60 });
  let clockId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];
  try {
    const { prisma, stripe, webhookService } = await loadCeopro();
    const frozen = Math.floor(Date.now() / 1000) - 60;
    const clock = await stripe.testHelpers.testClocks.create({
      name: `CEOPRO renewal ${fixture.run}`,
      frozen_time: frozen,
    });
    clockId = clock.id;

    const { customer, paymentMethodId } = await createStripeCustomerWithPaymentMethod({
      run: fixture.run,
      tenantId: fixture.tenantId,
      testClockId: clock.id,
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
    const initialStart = subscription.items.data[0].current_period_start;
    const initialEnd = subscription.items.data[0].current_period_end;

    const initialEvent = makeEvent({ type: "customer.subscription.created", object: subscription });
    eventIds.push(initialEvent.id);
    assert.equal((await webhookService(initialEvent)).success, true);

    await stripe.testHelpers.testClocks.advance(clock.id, {
      frozen_time: initialEnd + 60 * 60,
    });
    await waitFor(
      "Stripe Test Clock to become ready",
      () => stripe.testHelpers.testClocks.retrieve(clock.id),
      (value) => value.status === "ready",
      120_000,
      2_000,
    );

    const renewed = await waitFor(
      "subscription billing period to advance",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.items.data[0].current_period_start > initialStart,
      120_000,
      2_000,
    );

    const renewalEvent = makeEvent({ type: "customer.subscription.updated", object: renewed });
    eventIds.push(renewalEvent.id);
    assert.equal((await webhookService(renewalEvent)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(
      Math.floor(local.currentPeriodStart.getTime() / 1000),
      renewed.items.data[0].current_period_start,
    );

    const allocations = await prisma.subscriptionUsage.findMany({
      where: { subscription_id: local.id, feature_id: fixture.featureId },
      orderBy: { period_start: "asc" },
    });
    assert.equal(allocations.length, 2, "renewal should preserve old allocation and create one new period allocation");
    assert.notEqual(allocations[0].period_start.getTime(), allocations[1].period_start.getTime());
  } finally {
    const { prisma } = await loadCeopro();
    if (eventIds.length) {
      await prisma.payment_providerWebhookEvent.deleteMany({
        where: { payment_providerEventId: { in: eventIds } },
      });
    }
    await cleanupFixture({
      ...fixture,
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      stripeTestClockIds: clockId ? [clockId] : [],
    });
    await disconnectDb();
  }
});
