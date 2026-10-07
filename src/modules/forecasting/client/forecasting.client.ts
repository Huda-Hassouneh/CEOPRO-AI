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
  result: z.object({
    status: z.string().trim().min(1),
    source: z.enum(["xgboost", "baseline"]),
    expected_demand: z.number().finite().nonnegative(),
    forecast_target_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    confidence_score: z.number().finite().min(0).max(1),
    data_sufficiency: z.unknown()
  }),
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
  category: string | null;
  productName: string;
};

export { isAiIntegrationError as isForecastingClientError };

export function buildForecastData(input: ForecastRequestInput): unknown[] {
  return [
    input.transactions,
    input.horizonDays,
    input.currentPrice,
    input.currentStock,
    input.category,
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
  return parsed.data;
}
