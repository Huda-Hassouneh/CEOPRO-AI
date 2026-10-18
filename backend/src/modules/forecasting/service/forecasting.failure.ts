import type { AiIntegrationError } from "../../../integrations/ai/ai.types.js";

/** Only fixed diagnostic codes leave this boundary; never include upstream bodies or inputs. */
export function forecastFailureDetails(error: AiIntegrationError) {
  let reason = "FORECAST_AI_INVALID_RESPONSE";
  if (error.kind === "configuration") reason = error.message === "HUGGINGFACE_ACCESS_TOKEN is required for the AI service."
    ? "FORECAST_AI_TOKEN_MISSING" : "FORECAST_AI_CONFIGURATION";
  else if (error.kind === "network") reason = "FORECAST_AI_CONNECTION_FAILED";
  else if (error.kind === "timeout") reason = "FORECAST_AI_TIMEOUT";
  else if (error.kind === "upstream_event") reason = "FORECAST_AI_EXECUTION_FAILED";
  else if (error.kind === "upstream_http") reason = error.upstreamStatus === 401 || error.upstreamStatus === 403
    ? "FORECAST_AI_AUTHENTICATION_FAILED" : error.upstreamStatus === 429 ? "FORECAST_AI_RATE_LIMITED" : "FORECAST_AI_HTTP_ERROR";
  else if (error.message === "Forecast target does not match the supplied history and horizon.") reason = "FORECAST_AI_TARGET_MISMATCH";
  else if (error.message === "Forecasting returned a different product.") reason = "FORECAST_AI_PRODUCT_MISMATCH";
  const stage = error.kind === "configuration" ? "configuration"
    : error.message.startsWith("Hugging Face") ? "authentication"
    : error.message.startsWith("Gradio job submission") ? "submission"
    : error.message.includes("SSE") || error.message.startsWith("Gradio result retrieval") || error.kind === "upstream_event" ? "result"
    : "validation";
  return { service: "AI forecasting service", reason, failure_kind: error.kind, stage, upstream_status: error.upstreamStatus ?? null };
}
