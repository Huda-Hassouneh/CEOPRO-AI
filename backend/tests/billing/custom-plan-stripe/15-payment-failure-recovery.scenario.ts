import test from "node:test";
import assert from "node:assert/strict";
import {
  assertStripeTestEnvironment,
  cleanupFixture,
  createBaseAcceptedPlan,
  disconnectDb,
  loadCeopro,
  makeEvent,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("15.01 declined initial payment stays non-entitled, records failure, then recovers to active", async () => {
  const fixture = await createBaseAcceptedPlan({ finalPriceJod: 20, limitValue: 90 });
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];
  try {
    const { prisma, stripe, webhookService } = await loadCeopro();
    const declinedId = process.env.STRIPE_E2E_DECLINED_PAYMENT_METHOD || "pm_card_chargeCustomerFail";

    const customer = await stripe.customers.create({
      email: `declined-${fixture.run}@example.test`,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
    });
    customerId = customer.id;
    const declined = await stripe.paymentMethods.attach(declinedId, { customer: customer.id });
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: declined.id },
    });

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.stripePriceId }],
      default_payment_method: declined.id,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "default_incomplete",
      expand: ["latest_invoice"],
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "incomplete");

    const createdEvent = makeEvent({ type: "customer.subscription.created", object: subscription });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    const localBefore = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(localBefore.status, "pending");
    assert.equal(
      await prisma.subscriptionUsage.count({ where: { subscription_id: localBefore.id } }),
      0,
      "incomplete payment must not grant metered allocation",
    );

    const invoiceId =
      typeof subscription.latest_invoice === "string"
        ? subscription.latest_invoice
        : subscription.latest_invoice?.id;
    assert.ok(invoiceId, "failed initial subscription must have an invoice");
    const invoice = await stripe.invoices.retrieve(invoiceId!);

    const failedEvent = makeEvent({ type: "invoice.payment_failed", object: invoice });
    eventIds.push(failedEvent.id);
    assert.equal((await webhookService(failedEvent)).success, true);

    const failedPayment = await prisma.paymentTransaction.findFirst({
      where: { subscriptionId: localBefore.id, payment_providerInvoiceId: invoice.id },
    });
    assert.equal(failedPayment?.status, "failed");
    assert.ok(failedPayment?.failureReason);

    const valid = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: valid.id },
    });
    await stripe.subscriptions.update(subscription.id, { default_payment_method: valid.id });
    await stripe.invoices.pay(invoice.id, { payment_method: valid.id });

    const recovered = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(recovered.status, "active");
    const updatedEvent = makeEvent({ type: "customer.subscription.updated", object: recovered });
    eventIds.push(updatedEvent.id);
    assert.equal((await webhookService(updatedEvent)).success, true);

    const localAfter = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(localAfter.status, "active");
    assert.equal(
      await prisma.subscriptionUsage.count({
        where: { subscription_id: localAfter.id, feature_id: fixture.featureId },
      }),
      1,
      "recovered active subscription must receive its allocation",
    );
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
    });
    await disconnectDb();
  }
});
