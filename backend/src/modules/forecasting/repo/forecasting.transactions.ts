// maxWait covers acquiring/starting the transaction; timeout covers its work.
// The AI request stays outside these transactions. Keep both limits bounded.
export const FORECAST_TRANSACTION_OPTIONS = {
  maxWait: 10_000,
  timeout: 30_000
} as const;

export function isForecastTransactionStartTimeout(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { code?: unknown; message?: unknown; meta?: { error?: unknown } };
  return candidate.code === "P2028" &&
    [candidate.message, candidate.meta?.error].some((message) =>
      typeof message === "string" &&
      message.includes("Unable to start a transaction in the given time")
    );
}
