import {
  createAiIntegrationError,
  type AiServiceName,
  type GradioRuntimeConfig
} from "./ai.types.js";

const DEFAULT_SPACES = {
  models: {
    id: "hhuuddaa/ceopro-ai-models",
    url: "https://hhuuddaa-ceopro-ai-models.hf.space"
  },
  analytics: {
    id: "hhuuddaa/ceopro-ai-analytics",
    url: "https://hhuuddaa-ceopro-ai-analytics.hf.space"
  }
} as const;

export function getGradioRuntimeConfig(
  service: AiServiceName,
  env: NodeJS.ProcessEnv = process.env
): GradioRuntimeConfig {
  if (
    env.AI_SERVICE_USE_MOCKS?.trim().toLowerCase() === "true" &&
    env.NODE_ENV === "production"
  ) {
    throw createAiIntegrationError(
      "AI mock mode is disabled in production.",
      "configuration"
    );
  }

  const huggingFaceAccessToken = env.HUGGINGFACE_ACCESS_TOKEN?.trim();
  if (!huggingFaceAccessToken) {
    throw createAiIntegrationError(
      "HUGGINGFACE_ACCESS_TOKEN is required for the AI service.",
      "configuration"
    );
  }

  const defaults = DEFAULT_SPACES[service];
  const prefix = service === "models" ? "AI_MODELS" : "AI_ANALYTICS";
  const spaceId = env[`${prefix}_SPACE`]?.trim() || defaults.id;
  const baseUrl = env[`${prefix}_SPACE_URL`]?.trim() || defaults.url;
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(baseUrl);
  } catch {
    throw createAiIntegrationError(
      `${prefix}_SPACE_URL must be a valid HTTP or HTTPS URL.`,
      "configuration"
    );
  }

  if (
    !["http:", "https:"].includes(parsedUrl.protocol) ||
    (env.NODE_ENV === "production" && parsedUrl.protocol !== "https:")
  ) {
    throw createAiIntegrationError(
      `${prefix}_SPACE_URL must use HTTPS in production.`,
      "configuration"
    );
  }

  const timeoutMs = Number(env.AI_SERVICE_TIMEOUT_MS ?? 180_000);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 600_000) {
    throw createAiIntegrationError(
      "AI_SERVICE_TIMEOUT_MS must be an integer between 1000 and 600000.",
      "configuration"
    );
  }

  return {
    huggingFaceAccessToken,
    service: {
      spaceId,
      baseUrl: parsedUrl.toString().replace(/\/$/, "")
    },
    huggingFaceApiUrl: (env.HUGGINGFACE_API_URL || "https://huggingface.co")
      .trim()
      .replace(/\/$/, ""),
    tokenExpiresInSeconds: 3600,
    timeoutMs
  };
}

export function isAiMockModeEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const enabled = env.AI_SERVICE_USE_MOCKS?.trim().toLowerCase() === "true";
  if (enabled && env.NODE_ENV === "production") {
    throw createAiIntegrationError(
      "AI mock mode is disabled in production.",
      "configuration"
    );
  }
  return enabled;
}
