import { Prisma } from "../../../generated/prisma/client.js";

/**
 * Currency actually sent to Stripe for custom plans.
 *
 * CEO PRO can continue pricing/storing the commercial plan in JOD,
 * while Stripe charges the converted USD equivalent.
 */
export const CUSTOM_PLAN_PAYMENT_CURRENCY = "USD";

type DecimalInput = ConstructorParameters<typeof Prisma.Decimal>[0];

function decimal(value: DecimalInput) {
  return new Prisma.Decimal(value);
}

type ConvertCustomPlanPaymentAmountInput = {
  amount: number;

  /**
   * Commercial currency of the quote.
   * Example: JOD
   */
  quoteCurrency: string;

  /**
   * Snapshot FX data stored with the quote.
   *
   * Example:
   * source = USD
   * target = JOD
   * rate   = 0.709
   *
   * Means:
   *
   * 1 USD = 0.709 JOD
   */
  fxRate: DecimalInput | null | undefined;
  fxSourceCurrency: string | null | undefined;
  fxTargetCurrency: string | null | undefined;
};

/**
 * Convert the commercial quote amount into the currency Stripe accepts.
 *
 * Example:
 *
 * Quote:
 *   100 JOD
 *
 * FX:
 *   1 USD = 0.709 JOD
 *
 * Stripe:
 *   100 / 0.709 = 141.04 USD
 */
export function convertCustomPlanAmountToPaymentCurrency(
  input: ConvertCustomPlanPaymentAmountInput,
): number {
  if (!Number.isFinite(input.amount) || input.amount < 0) {
    throw new Error("Invalid custom-plan payment amount.");
  }

  const quoteCurrency = input.quoteCurrency.trim().toUpperCase();

  const paymentCurrency = CUSTOM_PLAN_PAYMENT_CURRENCY;

  /*
   * No conversion required.
   */
  if (quoteCurrency === paymentCurrency) {
    return Number(input.amount.toFixed(2));
  }

  const sourceCurrency = input.fxSourceCurrency?.trim().toUpperCase() ?? null;

  const targetCurrency = input.fxTargetCurrency?.trim().toUpperCase() ?? null;

  if (input.fxRate == null) {
    throw new Error(
      `Missing payment FX rate for ${quoteCurrency} -> ${paymentCurrency}`,
    );
  }

  const rate = decimal(input.fxRate);

  if (rate.lessThanOrEqualTo(0)) {
    throw new Error("Payment FX rate must be greater than zero.");
  }

  const amount = decimal(input.amount);

  let converted: Prisma.Decimal;

  /*
   * Example:
   *
   * FX stored as:
   * USD -> JOD
   *
   * 1 USD = 0.709 JOD
   *
   * Quote amount:
   * 100 JOD
   *
   * Convert JOD -> USD:
   *
   * 100 / 0.709
   */
  if (sourceCurrency === paymentCurrency && targetCurrency === quoteCurrency) {
    converted = amount.div(rate);
  } else if (

  /*
   * Also support the opposite representation:
   *
   * FX stored as:
   * JOD -> USD
   *
   * Then:
   *
   * JOD amount * rate
   */
    sourceCurrency === quoteCurrency &&
    targetCurrency === paymentCurrency
  ) {
    converted = amount.mul(rate);
  } else {
    throw new Error(
      `FX configuration does not support payment conversion ${quoteCurrency} -> ${paymentCurrency}. ` +
        `Configured pair is ${sourceCurrency ?? "NONE"} -> ${targetCurrency ?? "NONE"}.`,
    );
  }

  /*
   * Stripe USD Price uses cents, therefore two decimals
   * at the major-unit level are enough before stripeService
   * converts it into minor units.
   */
  return Number(converted.toDecimalPlaces(2).toString());
}
