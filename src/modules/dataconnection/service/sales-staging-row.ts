const PRICE_SCALE = 4n;
const DISCOUNT_SCALE = 2n;
const PRICE_FACTOR = 10n ** PRICE_SCALE;
const DISCOUNT_FACTOR = 10n ** DISCOUNT_SCALE;
const MAX_NUMERIC_12_4 = 10n ** 12n - 1n;

export type SalesStagingRow = {
  productName: string;
  quantity: number;
  unitPrice: string;
  totalPrice: string;
  currency: string;
  transactionDate: Date;
};

export type SalesStagingRowParse =
  | { ok: true; value: SalesStagingRow }
  | { ok: false; error: string };

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const normalized = String(value).trim();
  return normalized || null;
}

function scaledDecimal(value: unknown, scale: bigint, maxWholeDigits: number): bigint | null {
  const raw = text(value);
  if (!raw) return null;
  const decimals = Number(scale.toString().length - 1);
  const expression = new RegExp(
    `^(\\d{1,${maxWholeDigits}})(?:\\.(\\d{1,${decimals}}))?$`
  );
  const match = raw.match(expression);
  if (!match) return null;
  const fraction = (match[2] ?? "").padEnd(decimals, "0");
  return BigInt(match[1]!) * scale + BigInt(fraction || "0");
}

function decimalString(value: bigint, scale: bigint): string {
  const whole = value / scale;
  const precision = Number(scale.toString().length - 1);
  const fraction = (value % scale).toString().padStart(precision, "0");
  return `${whole}.${fraction}`;
}

function parseDate(value: unknown): Date | null {
  const raw = text(value);
  if (!raw) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const parsed = new Date(`${raw}T00:00:00.000Z`);
    return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== raw
      ? null
      : parsed;
  }

  const normalized = raw.includes(" ") ? raw.replace(" ", "T") : raw;
  const hasExplicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const candidate = hasExplicitZone ? normalized : `${normalized}Z`;
  const parsed = new Date(candidate);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function computedTotalPrice(unitPrice: bigint, quantity: number, discount: bigint): bigint {
  const undiscounted = unitPrice * BigInt(quantity);
  const afterDiscount = undiscounted * (10000n - discount);
  return (afterDiscount + 5000n) / 10000n;
}

/** Validates the sales fields again at the persistence boundary. */
export function parseSalesStagingRow(input: unknown): SalesStagingRowParse {
  const fields = record(input);
  if (!fields) return { ok: false, error: "Staged payload must be a JSON object." };

  const productName = text(fields.product_name);
  if (!productName) return { ok: false, error: "product_name is required." };

  const rawQuantity = text(fields.quantity);
  const quantity = rawQuantity && /^\d{1,9}$/.test(rawQuantity) ? Number(rawQuantity) : NaN;
  if (!Number.isSafeInteger(quantity) || quantity <= 0) {
    return { ok: false, error: "quantity must be a positive integer." };
  }

  const unitPrice = scaledDecimal(fields.unit_price, PRICE_FACTOR, 8);
  if (unitPrice === null) {
    return { ok: false, error: "unit_price must be a non-negative decimal with at most 4 decimal places." };
  }

  const currencyValue = text(fields.currency)?.toUpperCase();
  if (!currencyValue || !/^[A-Z]{3}$/.test(currencyValue)) {
    return { ok: false, error: "currency must be a 3-letter ISO currency code." };
  }

  const transactionDate = parseDate(fields.transaction_date);
  if (!transactionDate) {
    return { ok: false, error: "transaction_date must be a valid ISO date or timestamp." };
  }

  let totalPrice: bigint;
  const amountRaw = text(fields.amount_raw);
  if (amountRaw) {
    const parsedAmount = scaledDecimal(amountRaw, PRICE_FACTOR, 8);
    if (parsedAmount === null) {
      return { ok: false, error: "amount_raw must be a non-negative decimal with at most 4 decimal places." };
    }
    totalPrice = parsedAmount;
  } else {
    const rawDiscount =
      fields.discount_pct === undefined ||
      fields.discount_pct === null ||
      fields.discount_pct === ""
        ? "0"
        : fields.discount_pct;
    const discount = scaledDecimal(rawDiscount, DISCOUNT_FACTOR, 3);
    if (discount === null || discount > 100n * DISCOUNT_FACTOR) {
      return { ok: false, error: "discount_pct must be between 0 and 100." };
    }
    totalPrice = computedTotalPrice(unitPrice, quantity, discount);
  }

  if (totalPrice > MAX_NUMERIC_12_4) {
    return { ok: false, error: "total_price exceeds the database precision limit." };
  }

  return {
    ok: true,
    value: {
      productName,
      quantity,
      unitPrice: decimalString(unitPrice, PRICE_FACTOR),
      totalPrice: decimalString(totalPrice, PRICE_FACTOR),
      currency: currencyValue,
      transactionDate
    }
  };
}
