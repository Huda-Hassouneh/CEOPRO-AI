import { test } from "node:test";
import assert from "node:assert/strict";
import { optionPrice, validatePlanOptions } from "../src/modules/subscription/service/plan-pricing.ts";

test("monthly, quarterly and semiannual prices are the actual renewal totals", () => {
  const options = validatePlanOptions([
    { period: "monthly", months: 1, discountPercent: 0 },
    { period: "three-months", months: 3, discountPercent: 10 },
    { period: "six-months", months: 6, discountPercent: 20 }
  ], 10, 1, "month");
  assert.deepEqual(options.map((item) => [item.intervalUnit, item.intervalCount,
    optionPrice(10, 1, "month", item)]),
    [["month", 1, 10], ["month", 3, 27], ["month", 6, 48]]);
});

test("annual base amount can be priced monthly at a fixed 12:1 ratio", () => {
  const [monthly, yearly] = validatePlanOptions([
    { period: "monthly", intervalUnit: "month", intervalCount: 1, discountPercent: 0 },
    { period: "yearly", intervalUnit: "year", intervalCount: 1, discountPercent: 10 }
  ], 120, 1, "year");
  assert.equal(optionPrice(120, 1, "year", monthly), 10);
  assert.equal(optionPrice(120, 1, "year", yearly), 108);
});

test("daily plans use day renewal and cannot imply a calendar month length", () => {
  const [weekly] = validatePlanOptions([
    { period: "seven-days", intervalUnit: "day", intervalCount: 7, discountPercent: 0 }
  ], 5, 1, "day");
  assert.equal(optionPrice(5, 1, "day", weekly), 35);
  assert.throws(() => validatePlanOptions([
    { period: "monthly", months: 1, discountPercent: 0 }
  ], 5, 1, "day"), /cannot be combined/);
});

test("duplicate codes and invalid Stripe recurrence are rejected before price creation", () => {
  assert.throws(() => validatePlanOptions([
    { period: "monthly", months: 1, discountPercent: 0 },
    { period: "monthly", months: 3, discountPercent: 0 }
  ], 10, 1, "month"), /unique/);
  assert.throws(() => validatePlanOptions([
    { period: "four-years", intervalUnit: "year", intervalCount: 4, discountPercent: 0 }
  ], 10, 1, "month"), /Stripe interval/);
});

test("catalog amount uses the same minor-unit rounding that Stripe charges", () => {
  const [option] = validatePlanOptions([
    { period: "monthly", months: 1, discountPercent: 0 }
  ], 10.5, 1, "month", "JPY");
  assert.equal(optionPrice(10.5, 1, "month", option, "JPY"), 11);
});
