import test from "node:test";
import assert from "node:assert/strict";
import {
  assertProductionPlanTestEnvironment,
  cleanupStandardPlanFixture,
  createStandardPlanFixture,
  disconnectProductionPlanDb,
  loadProductionPlans,
} from "./_production-plan-helpers.js";

assertProductionPlanTestEnvironment();

test("31.01 standard-plan checkout uses the server-owned Stripe Price and tenant metadata", async () => {
  const fixture = await createStandardPlanFixture({ basePriceUsd: 30 });
  const customerIds: string[] = [];
  try {
    const { stripe, checkoutService } = await loadProductionPlans();
    const result = await checkoutService(
      {
        planId: fixture.planId,
        billing_period: "monthly",
        payment_method: "stripe",
      },
      {
        id: fixture.userId,
        email: fixture.email,
        tenant_id: fixture.tenantId,
      },
    );
    assert.equal(result.success, true);
    assert.ok(result.data?.checkoutUrl?.startsWith("https://checkout.stripe.com/"));

    const sessionId = new URL(result.data.checkoutUrl).pathname.split("/").filter(Boolean).at(-1)!;
    const session = await stripe.checkout.sessions.retrieve(sessionId, { expand: ["line_items"] });
    const customerId = typeof session.customer === "string" ? session.customer : session.customer?.id;
    if (customerId) customerIds.push(customerId);

    assert.equal(session.mode, "subscription");
    assert.equal(session.client_reference_id, fixture.tenantId);
    assert.equal(session.metadata?.tenantId, fixture.tenantId);
    assert.equal(session.line_items?.data[0]?.price?.id, fixture.priceIds[0]);
    assert.equal(session.amount_subtotal, 3000);
    assert.equal(session.amount_total, 3000);
  } finally {
    await cleanupStandardPlanFixture(fixture, { stripeCustomerIds: customerIds });
    await disconnectProductionPlanDb();
  }
});
