import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e/ai-pricing",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  timeout: 90_000,
  reporter: [
    ["list"],
    ["html", { outputFolder: "tests/reports/ai-pricing/html", open: "never" }],
    ["json", { outputFile: "tests/reports/ai-pricing/playwright-report.json" }],
    ["./tests/support/diagnostics/dashboard-reporter.ts", { outputFile: "tests/reports/ai-pricing/diagnostics.json" }]
  ],
  outputDir: "tests/reports/ai-pricing/artifacts",
  use: {
    baseURL: process.env.MARKET_INTELLIGENCE_TEST_FRONTEND_URL || "http://127.0.0.1:5173",
    browserName: "chromium",
    headless: process.env.DASHBOARD_TEST_HEADED !== "1",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  }
});
