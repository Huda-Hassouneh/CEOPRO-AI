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

test("17.01 Stripe TEST Checkout applies the CEOPRO promo coupon to the custom-plan provider amount", async () => {
  const fixture = await createBaseAcceptedPlan({ finalPriceJod: 100, limitValue: 30 });
  let couponId: string | undefined;
  let promoCodeId: string | undefined;
  let customerId: string | undefined;
  try {
    const { prisma, stripe, checkoutService } = await loadCeopro();
    const coupon = await stripe.coupons.create({
      percent_off: 10,
      duration: "once",
      name: `CEOPRO E2E 10% ${fixture.run}`,
    });
    couponId = coupon.id;

    const promo = await prisma.promoCode.create({
      data: {
        code: `E2E${fixture.run.toUpperCase()}`,
        discountType: "percentage",
        discountValue: 10,
        maxUses: 100,
        maxUsesPerUser: 1,
        paymentProviderCoupon: coupon.id,
        startsAt: new Date(Date.now() - 60_000),
        expiresAt: new Date(Date.now() + 60 * 60 * 1000),
        isActive: true,
      },
    });
    promoCodeId = promo.id;
    await prisma.promoCodePlan.create({ data: { promoCodeId: promo.id, planId: fixture.planId } });

    const result = await checkoutService(
      {
        planId: fixture.planId,
        billing_period: "monthly",
        payment_method: "stripe",
        promoCode: promo.code,
      },
      {
        id: "22222222-2222-4222-8222-222222222222",
        email: `promo-${fixture.run}@example.test`,
        tenant_id: fixture.tenantId,
      },
    );
    assert.equal(result.success, true);
    const sessionId = new URL(result.data!.checkoutUrl).pathname.split("/").filter(Boolean).at(-1)!;
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    const cid = typeof session.customer === "string" ? session.customer : session.customer?.id;
    if (cid) customerId = cid;

    assert.ok(session.amount_subtotal && session.amount_subtotal > 0);
    assert.ok(session.total_details?.amount_discount && session.total_details.amount_discount > 0);
    assert.equal(
      session.amount_total,
      session.amount_subtotal - session.total_details!.amount_discount,
    );
    const expectedDiscount = Math.round(session.amount_subtotal * 0.1);
    assert.ok(
      Math.abs(session.total_details!.amount_discount - expectedDiscount) <= 1,
      "Stripe discount should be approximately 10% after minor-unit rounding",
    );
  } finally {
    await cleanupFixture({
      ...fixture,
      stripeCustomerIds: customerId ? [customerId] : [],
      stripeCouponIds: couponId ? [couponId] : [],
      promoCodeIds: promoCodeId ? [promoCodeId] : [],
    });
    await disconnectDb();
  }
});
