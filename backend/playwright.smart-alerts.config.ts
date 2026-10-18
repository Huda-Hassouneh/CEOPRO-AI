import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e/smart-alerts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  timeout: 45_000,
  reporter: [
    ["list"],
    ["html", { outputFolder: "tests/reports/smart-alerts/html", open: "never" }],
    ["json", { outputFile: "tests/reports/smart-alerts/playwright-report.json" }],
    ["./tests/support/diagnostics/dashboard-reporter.ts", { outputFile: "tests/reports/smart-alerts/diagnostics.json" }]
  ],
  outputDir: "tests/reports/smart-alerts/artifacts",
  use: {
    baseURL: process.env.DASHBOARD_TEST_FRONTEND_URL || "http://127.0.0.1:5173",
    browserName: "chromium",
    headless: process.env.DASHBOARD_TEST_HEADED !== "1",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  }
});
