import test from "node:test";
import assert from "node:assert/strict";
import {
  assertStripeTestEnvironment,
  cleanupFixture,
  createBaseAcceptedPlan,
  disconnectDb,
  loadCeopro,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("12.01 real Stripe TEST checkout matches the accepted custom-plan price and tenant", async () => {
  const fixture = await createBaseAcceptedPlan({ finalPriceJod: 100, limitValue: 40 });
  const customerIds: string[] = [];
  try {
    const { prisma, stripe, checkoutService } = await loadCeopro();
    const checkout = await checkoutService(
      { planId: fixture.planId, billing_period: "monthly", payment_method: "stripe" },
      {
        id: "11111111-1111-4111-8111-111111111111",
        email: `checkout-${fixture.run}@example.test`,
        tenant_id: fixture.tenantId,
      },
    );

    assert.equal(checkout.success, true);
    assert.ok(checkout.data?.checkoutUrl?.startsWith("https://checkout.stripe.com/"));

    const sessionId = new URL(checkout.data.checkoutUrl).pathname.split("/").filter(Boolean).at(-1)!;
    const session = await stripe.checkout.sessions.retrieve(sessionId, { expand: ["line_items"] });
    const customerId = typeof session.customer === "string" ? session.customer : session.customer?.id;
    if (customerId) customerIds.push(customerId);

    assert.equal(session.mode, "subscription");
    assert.equal(session.client_reference_id, fixture.tenantId);
    assert.equal(session.metadata?.tenantId, fixture.tenantId);

    const plan = await prisma.plan.findUniqueOrThrow({ where: { id: fixture.planId } });
    const option = (plan.billingOptions as Array<any>).find((item) => item.period === "monthly");
    assert.ok(option?.stripePriceId);
    const price = await stripe.prices.retrieve(option.stripePriceId);

    assert.equal(price.currency.toUpperCase(), "USD");
    assert.equal(session.line_items?.data[0]?.price?.id, price.id);
    assert.equal(session.amount_subtotal, price.unit_amount);
    assert.equal(session.amount_total, price.unit_amount);
  } finally {
    await cleanupFixture({ ...fixture, stripeCustomerIds: customerIds });
    await disconnectDb();
  }
});
