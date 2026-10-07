export type BootstrapExecutionMode = {
  dryRun: boolean;
  verifyOnly: boolean;
};
export function displayDatabaseTarget(): string {
  const raw = process.env.DATABASE_URL;
  if (!raw) return "DATABASE_URL is not configured";
  try {
    const parsed = new URL(raw);
    return `${parsed.hostname}:${parsed.port || "5432"}${parsed.pathname}`;
  } catch {
    return "configured DATABASE_URL";
  }
}
export function assertSafeEnvironment(mode: BootstrapExecutionMode): void {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is required.");
  }
  const stripeKey = (process.env.STRIPE_SECRET_KEY || "").trim();
  if (!stripeKey) {
    throw new Error("STRIPE_SECRET_KEY is required.");
  }
  if (
    stripeKey.startsWith("sk_live_") &&
    process.env.CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP !== "YES"
  ) {
    throw new Error(
      "Refusing to write live Stripe Prices. Set CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP=YES only for an intentional production catalog deployment."
    );
  }
  if (
    process.env.NODE_ENV === "production" &&
    !mode.dryRun &&
    !mode.verifyOnly &&
    process.env.CONFIRM_PRODUCTION_PLAN_BOOTSTRAP !== "YES"
  ) {
    throw new Error(
      "Refusing to mutate the production plan catalog without CONFIRM_PRODUCTION_PLAN_BOOTSTRAP=YES."
    );
  }
}
