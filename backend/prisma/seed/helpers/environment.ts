export function getDatabaseName(): string {
  const url = process.env.DATABASE_URL;
  return url ? decodeURIComponent(new URL(url).pathname.slice(1)) : "";
}

export function assertDevelopmentSeedEnvironment(context = "seed"): void {
  const databaseName = getDatabaseName();

  if (
    process.env.NODE_ENV === "production" ||
    !/test|dev/i.test(databaseName)
  ) {
    throw new Error(
      `Refusing to ${context}: DATABASE_URL database name must contain TEST or DEV and NODE_ENV must not be production.`
    );
  }
}

export function requireSeedPassword(): string {
  const password = process.env.SEED_DEV_PASSWORD;

  if (!password || password.length < 12) {
    throw new Error(
      "Set SEED_DEV_PASSWORD (12+ characters); no default password is embedded in the fixtures."
    );
  }

  return password;
}

export function requireDashboardTenantId(): string {
  const tenantId = process.env.DASHBOARD_TEST_TENANT_ID?.trim();

  if (
    !tenantId ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      tenantId
    )
  ) {
    throw new Error(
      "Set DASHBOARD_TEST_TENANT_ID to the UUID of the tenant whose dashboard you are testing."
    );
  }

  return tenantId;
}

export function getDashboardPeriodDays(): 7 | 30 | 90 {
  const periodDays = Number(process.env.DASHBOARD_TEST_PERIOD_DAYS ?? 30);

  if (![7, 30, 90].includes(periodDays)) {
    throw new Error(
      "DASHBOARD_TEST_PERIOD_DAYS must be 7, 30, or 90 (default 30)."
    );
  }

  return periodDays as 7 | 30 | 90;
}

export function assertDashboardArguments(args: string[]): { clean: boolean } {
  if (args.some((arg) => arg !== "--clean")) {
    throw new Error("The only supported dashboard seed argument is --clean.");
  }

  return { clean: args.includes("--clean") };
}
