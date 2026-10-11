import { defineConfig } from "@playwright/test";

const baseURL = process.env.DASHBOARD_TEST_FRONTEND_URL || "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "tests/reports/e2e/html", open: "never" }],
    ["json", { outputFile: "tests/reports/e2e/playwright-report.json" }],
    ["./tests/support/diagnostics/dashboard-reporter.ts", { outputFile: "tests/reports/e2e/diagnostics.json" }]
  ],
  outputDir: "tests/reports/e2e/artifacts",
  use: {
    baseURL,
    browserName: "chromium",
    headless: process.env.DASHBOARD_TEST_HEADED !== "1",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000
  }
});
