import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";

const forecastResponseSchema = z.object({
  product_name: z.string().trim().min(1),
  transactions_used: z.number().int().nonnegative(),
  result: z.union([z.object({
    status: z.literal("OK"),
    source: z.enum(["xgboost", "baseline"]),
    expected_demand: z.number().finite().nonnegative().max(2_147_483_647),
    forecast_target_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    confidence_score: z.number().finite().min(0).max(1).nullable().optional(),
    confidence_range_lower: z.number().finite().nonnegative().max(9_999_999_999.99).nullable().optional(),
    confidence_range_upper: z.number().finite().nonnegative().max(9_999_999_999.99).nullable().optional(),
    model_version: z.string().trim().min(1).max(50).nullable().optional(),
    model_name: z.string().trim().min(1).nullable().optional(),
    data_sufficiency: z.unknown(),
    prediction_kind: z.literal("target_day").optional()
  }), z.object({
    status: z.literal("UNKNOWN"),
    data_sufficiency: z.unknown().optional()
  })]),
  persisted_records: z.array(z.unknown())
});

export type ForecastGradioResponse = z.infer<typeof forecastResponseSchema>;

export type ForecastTransactionInput = {
  transaction_date: string;
  quantity: number;
  unit_price: number;
  product_name?: string;
};

export type ForecastRequestInput = {
  transactions: ForecastTransactionInput[];
  horizonDays: number;
  currentPrice: number | null;
  currentStock: number | null;
  currency: string;
  productName: string;
};

export { isAiIntegrationError as isForecastingClientError };

function csvCell(value: string | number): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildForecastCsv(input: ForecastRequestInput): string {
  return [
    "product_name,quantity,unit_price,currency,transaction_date",
    ...input.transactions.map((row) => [
      input.productName, row.quantity, row.unit_price,
      input.currency.trim().toUpperCase(), row.transaction_date
    ].map(csvCell).join(","))
  ].join("\n");
}

export function buildForecastData(input: ForecastRequestInput): unknown[] {
  // /forecast is the typed API, not /forecast_ui. Its six positional inputs
  // are transactions, horizon_days, current_price, current_stock, category,
  // product_name. CSV/product/horizon/price/stock belongs to the UI endpoint.
  return [
    input.transactions.map((row) => ({
      transaction_date: row.transaction_date,
      quantity: row.quantity,
      unit_price: row.unit_price,
      product_name: input.productName
    })),
    input.horizonDays,
    input.currentPrice,
    input.currentStock,
    null,
    input.productName
  ];
}

export async function requestDemandForecast(
  input: ForecastRequestInput,
  client: GradioClient = gradioClient
): Promise<ForecastGradioResponse> {
  if (!Number.isInteger(input.horizonDays) || input.horizonDays < 1 || input.horizonDays > 60) {
    throw createAiIntegrationError(
      "Forecast horizon must be between 1 and 60 days.",
      "configuration"
    );
  }

  if (!/^[A-Z]{3}$/.test(input.currency.trim().toUpperCase())) {
    throw createAiIntegrationError("Forecast transactions require the product currency.", "configuration");
  }

  const payload = await client.call({
    service: "analytics",
    apiName: "forecast",
    data: buildForecastData(input)
  });
  const parsed = forecastResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw createAiIntegrationError(
      "Gradio forecasting response did not match the documented output schema.",
      "malformed_response"
    );
  }
  const result = parsed.data.result;
  if (parsed.data.product_name !== input.productName) {
    throw createAiIntegrationError("Forecasting returned a different product.", "malformed_response");
  }
  if (result.status === "OK") {
    const date = new Date(`${result.forecast_target_date}T00:00:00Z`);
    const lower = result.confidence_range_lower ?? null;
    const upper = result.confidence_range_upper ?? null;
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== result.forecast_target_date ||
        (lower === null) !== (upper === null) ||
        (lower !== null && upper !== null && (lower > result.expected_demand || upper < result.expected_demand))) {
      throw createAiIntegrationError("Forecasting returned an invalid date or confidence range.", "malformed_response");
    }
  }
  return parsed.data;
}
