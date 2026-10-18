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
  waitForLifecycle,
} from "./_subscription-lifecycle-helpers.js";

assertLifecycleTestEnvironment();

test("26.01 pending initial payment offers recovery on the existing subscription and blocks duplicate checkout", async () => {
  const fixture = await createLifecycleFixture();
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const {
      prisma,
      stripe,
      webhookService,
      createSubscriptionRecoveryService,
      checkoutService,
      getRemainingUsage,
    } = await loadLifecycle();

    const customer = await stripe.customers.create({
      email: `pending-${fixture.run}@example.test`,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
    });
    customerId = customer.id;

    const declined = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_DECLINED_PAYMENT_METHOD || "pm_card_chargeCustomerFail",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: declined.id },
    });

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: fixture.plans[0].stripePriceId }],
      default_payment_method: declined.id,
      metadata: { tenantId: fixture.tenantId, ceoproTestRun: fixture.run },
      payment_behavior: "default_incomplete",
      expand: ["latest_invoice"],
    });
    subscriptionId = subscription.id;
    assert.equal(subscription.status, "incomplete");

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    const invoiceId =
      typeof subscription.latest_invoice === "string"
        ? subscription.latest_invoice
        : subscription.latest_invoice?.id;
    assert.ok(invoiceId);
    const invoice = await stripe.invoices.retrieve(invoiceId!);

    const failedEvent = makeLifecycleEvent({
      type: "invoice.payment_failed",
      object: invoice,
    });
    eventIds.push(failedEvent.id);
    assert.equal((await webhookService(failedEvent)).success, true);

    const local = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(local.status, "pending");
    assert.equal(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode), null);

    const recovery = await createSubscriptionRecoveryService(fixture.tenantId);
    assert.equal(recovery.success, true);
    assert.equal(recovery.data?.type, "complete_payment");
    assert.ok(recovery.data?.url?.startsWith("http"));

    const checkout = await checkoutService(
      {
        planId: fixture.plans[0].id,
        billing_period: "monthly",
        payment_method: "card",
      } as any,
      {
        email: `pending-${fixture.run}@example.test`,
        id: randomUUID(),
        tenant_id: fixture.tenantId,
      },
    );
    assert.equal(checkout.success, false, "recovery state must not create a second subscription");
    assert.equal(checkout.code, "SUBSCRIPTION_ALREADY_EXISTS");

    const valid = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: valid.id },
    });
    await stripe.subscriptions.update(subscription.id, {
      default_payment_method: valid.id,
    });
    await stripe.invoices.pay(invoice.id, { payment_method: valid.id });

    const active = await stripe.subscriptions.retrieve(subscription.id);
    assert.equal(active.status, "active");
    const updatedEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: active,
    });
    eventIds.push(updatedEvent.id);
    assert.equal((await webhookService(updatedEvent)).success, true);
    assert.ok(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode));
  } finally {
    await cleanupLifecycleFixture(fixture, {
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeSubscriptionIds: subscriptionId ? [subscriptionId] : [],
      eventIds,
    });
    await disconnectLifecycleDb();
  }
});

test("26.02 failed renewal grants no fresh allocation until payment recovery succeeds", async () => {
  const fixture = await createLifecycleFixture();
  let clockId: string | undefined;
  let customerId: string | undefined;
  let subscriptionId: string | undefined;
  const eventIds: string[] = [];

  try {
    const {
      prisma,
      stripe,
      webhookService,
      createSubscriptionRecoveryService,
      getRemainingUsage,
    } = await loadLifecycle();

    const clock = await stripe.testHelpers.testClocks.create({
      name: `Lifecycle failed renewal ${fixture.run}`,
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

    const createdEvent = makeLifecycleEvent({
      type: "customer.subscription.created",
      object: subscription,
    });
    eventIds.push(createdEvent.id);
    assert.equal((await webhookService(createdEvent)).success, true);

    const localInitial = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    await prisma.subscriptionUsage.updateMany({
      where: {
        subscription_id: localInitial.id,
        feature_id: fixture.billingFeatureId,
      },
      data: { current_usage: 55 },
    });

    const declined = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_DECLINED_PAYMENT_METHOD || "pm_card_chargeCustomerFail",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: declined.id },
    });
    await stripe.subscriptions.update(subscription.id, {
      default_payment_method: declined.id,
    });

    const initialEnd = subscription.items.data[0].current_period_end;
    await stripe.testHelpers.testClocks.advance(clock.id, {
      frozen_time: initialEnd + 60 * 60,
    });
    await waitForLifecycle(
      "failed-renewal test clock",
      () => stripe.testHelpers.testClocks.retrieve(clock.id),
      (value) => value.status === "ready",
    );

    const pastDue = await waitForLifecycle(
      "subscription to become past_due after renewal failure",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.status === "past_due",
    );

    const updateEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: pastDue,
    });
    eventIds.push(updateEvent.id);
    assert.equal((await webhookService(updateEvent)).success, true);

    const invoices = await stripe.invoices.list({
      customer: customer.id,
      subscription: subscription.id,
      limit: 10,
    });
    const renewalInvoice = invoices.data.find(
      (invoice) => invoice.billing_reason === "subscription_cycle" && invoice.status === "open",
    );
    assert.ok(renewalInvoice, "failed renewal must leave an open renewal invoice");

    const failedEvent = makeLifecycleEvent({
      type: "invoice.payment_failed",
      object: renewalInvoice!,
    });
    eventIds.push(failedEvent.id);
    assert.equal((await webhookService(failedEvent)).success, true);

    const localFailed = await prisma.subscription.findUniqueOrThrow({
      where: { paymentProviderSubscriptionId: subscription.id },
    });
    assert.equal(localFailed.status, "past_due");
    assert.equal(await getRemainingUsage(fixture.tenantId, fixture.billingFeatureCode), null);

    const failedAllocations = await prisma.subscriptionUsage.findMany({
      where: {
        subscription_id: localFailed.id,
        feature_id: fixture.billingFeatureId,
      },
      orderBy: { period_start: "asc" },
    });
    assert.equal(
      failedAllocations.length,
      1,
      "failed renewal must not create a fresh usage allocation while access is blocked",
    );
    assert.equal(failedAllocations[0].current_usage, 55);

    const recovery = await createSubscriptionRecoveryService(fixture.tenantId);
    assert.equal(recovery.success, true);
    assert.equal(recovery.data?.type, "resolve_payment");
    assert.ok(recovery.data?.url?.startsWith("http"));

    const valid = await stripe.paymentMethods.attach(
      process.env.STRIPE_E2E_VALID_PAYMENT_METHOD || "pm_card_visa",
      { customer: customer.id },
    );
    await stripe.customers.update(customer.id, {
      invoice_settings: { default_payment_method: valid.id },
    });
    await stripe.subscriptions.update(subscription.id, {
      default_payment_method: valid.id,
    });
    await stripe.invoices.pay(renewalInvoice!.id, { payment_method: valid.id });

    const recovered = await waitForLifecycle(
      "renewal payment recovery",
      () => stripe.subscriptions.retrieve(subscription.id),
      (value) => value.status === "active",
    );
    const recoveredEvent = makeLifecycleEvent({
      type: "customer.subscription.updated",
      object: recovered,
    });
    eventIds.push(recoveredEvent.id);
    assert.equal((await webhookService(recoveredEvent)).success, true);

    const recoveredAllocations = await prisma.subscriptionUsage.findMany({
      where: {
        subscription_id: localFailed.id,
        feature_id: fixture.billingFeatureId,
      },
      orderBy: { period_start: "asc" },
    });
    assert.equal(recoveredAllocations.length, 2);
    assert.equal(recoveredAllocations[0].current_usage, 55);
    assert.equal(recoveredAllocations[1].current_usage, 0);
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
