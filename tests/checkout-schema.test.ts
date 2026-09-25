import test from "node:test";
import assert from "node:assert/strict";
import { checkoutSchema } from "../src/DTO/checkout.dto.js";

test("checkout contract retains payment_method and rejects unknown fields", () => {
  const result = checkoutSchema.safeParse({
    planId: "550e8400-e29b-41d4-a716-446655440000",
    billing_period: "monthly",
    payment_method: "card"
  });
  assert.equal(result.success, true);

  const legacyMismatch = checkoutSchema.safeParse({
    planId: "550e8400-e29b-41d4-a716-446655440000",
    billing_period: "monthly",
    payment_method: "card",
    payment_provider: "stripe"
  });
  assert.equal(legacyMismatch.success, false);
});
