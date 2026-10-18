import type { PlanBillingOptionType } from "../types/plans.types.js";
import { toStripeMinorUnits, fromStripeMinorUnits } from "../../../utils/currency.js";

export type IntervalUnit = "day" | "month" | "year";

export type ResolvedBillingOption = PlanBillingOptionType & {
  intervalUnit: IntervalUnit;
  intervalCount: number;
};

// Existing plans only stored `months`; their Stripe Prices renew in months.
export function resolveBillingOption(option: PlanBillingOptionType): ResolvedBillingOption {
  const intervalUnit = (option.intervalUnit || "month") as IntervalUnit;
  const intervalCount = option.intervalCount ?? option.months;
  if (!["day", "month", "year"].includes(intervalUnit) ||
      typeof intervalCount !== "number" || !Number.isInteger(intervalCount) || intervalCount < 1 ||
      intervalCount > { day: 1095, month: 36, year: 3 }[intervalUnit]) {
    throw new Error("Billing option must have a valid Stripe interval (at most three years).");
  }
  if (option.months !== undefined &&
      (intervalUnit === "day" || option.months !== intervalCount * (intervalUnit === "year" ? 12 : 1))) {
    throw new Error("Billing option months disagree with its recurring interval.");
  }
  return { ...option, intervalUnit, intervalCount,
    ...(intervalUnit === "day" ? {} : { months: intervalCount * (intervalUnit === "year" ? 12 : 1) }) };
}

export function optionPrice(
  basePrice: number,
  baseValue: number,
  baseUnit: string,
  option: ResolvedBillingOption,
  currency = "JOD"
): number {
  if (!Number.isInteger(baseValue) || baseValue < 1 ||
      !["day", "month", "year"].includes(baseUnit) ||
      !Number.isFinite(basePrice) || basePrice < 0 ||
      !Number.isFinite(option.discountPercent) || option.discountPercent < 0 || option.discountPercent > 100) {
    throw new Error("Invalid plan base price, interval, or option discount.");
  }
  // Calendar months and days have no fixed conversion. A day-based plan only
  // accepts day-based options; months and years use the exact 12:1 ratio.
  if ((baseUnit === "day") !== (option.intervalUnit === "day")) {
    throw new Error("Day-based billing cannot be combined with month or year options.");
  }
  const baseUnits = baseValue * (baseUnit === "year" ? 12 : 1);
  const optionUnits = option.intervalCount * (option.intervalUnit === "year" ? 12 : 1);
  const computed = basePrice * optionUnits / baseUnits * (1 - option.discountPercent / 100);
  const amount = fromStripeMinorUnits(toStripeMinorUnits(computed, currency), currency);
  if (amount > 99999999.99) throw new Error("Calculated Stripe price exceeds the supported amount.");
  return amount;
}

export function validatePlanOptions(options: PlanBillingOptionType[], basePrice: number, baseValue: number, baseUnit: string, currency = "JOD") {
  if (!options?.length) throw new Error("At least one billing option is required.");
  const codes = new Set<string>();
  return options.map((option) => {
    const period = option.period?.trim();
    if (!period || period.length > 100 || codes.has(period)) {
      throw new Error("Billing option period codes must be unique and nonempty.");
    }
    codes.add(period);
    const resolved = resolveBillingOption({ ...option, period });
    optionPrice(basePrice, baseValue, baseUnit, resolved, currency);
    return resolved;
  });
}
