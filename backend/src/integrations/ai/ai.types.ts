export type AiServiceName = "models" | "analytics";

export type AiIntegrationErrorKind =
  | "configuration"
  | "timeout"
  | "network"
  | "upstream_http"
  | "malformed_response"
  | "upstream_event";

export type AiIntegrationError = Error & {
  name: "AiIntegrationError";
  kind: AiIntegrationErrorKind;
  upstreamStatus?: number;
};

export type GradioServiceConfig = {
  spaceId: string;
  baseUrl: string;
};

export type GradioRuntimeConfig = {
  huggingFaceAccessToken: string;
  service: GradioServiceConfig;
  huggingFaceApiUrl: string;
  tokenExpiresInSeconds: number;
  timeoutMs: number;
};

export type GradioCallInput = {
  service: AiServiceName;
  apiName: string;
  data: readonly unknown[];
  timeoutMs?: number;
};

export type GradioClient = {
  call(input: GradioCallInput): Promise<unknown>;
};

export function createAiIntegrationError(
  message: string,
  kind: AiIntegrationErrorKind,
  upstreamStatus?: number
): AiIntegrationError {
  const error = new Error(message) as AiIntegrationError;
  error.name = "AiIntegrationError";
  error.kind = kind;
  error.upstreamStatus = upstreamStatus;
  return error;
}

export function isAiIntegrationError(
  error: unknown
): error is AiIntegrationError {
  return error instanceof Error && error.name === "AiIntegrationError";
}
