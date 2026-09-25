import test from "node:test";
import assert from "node:assert/strict";
import {
  fromStripeMinorUnits,
  getStripeCurrencyExponent,
  toStripeMinorUnits
} from "../src/utils/currency.js";

test("Stripe amount formatting uses zero-decimal exceptions and two decimals otherwise", () => {
  assert.equal(getStripeCurrencyExponent("USD"), 2);
  assert.equal(getStripeCurrencyExponent("JPY"), 0);
  assert.equal(getStripeCurrencyExponent("JOD"), 2);
});

test("major/minor conversion is symmetric for Stripe payment amounts", () => {
  assert.equal(toStripeMinorUnits(12.34, "USD"), 1234);
  assert.equal(fromStripeMinorUnits(1234, "USD"), 12.34);
  assert.equal(toStripeMinorUnits(500, "JPY"), 500);
  assert.equal(fromStripeMinorUnits(500, "JPY"), 500);
});
