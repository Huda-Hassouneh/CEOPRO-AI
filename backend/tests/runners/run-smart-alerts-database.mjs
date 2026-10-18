import { spawnSync } from "node:child_process";
import { basename } from "node:path";

const url = process.env.AI_TEST_DATABASE_URL || "";
const database = url ? decodeURIComponent(new URL(url).pathname.replace(/^\//, "")) : "";
const namedTestDb = /(^|[-_])(test|testing|qa|e2e)([-_]|$)/i.test(database);
const prerequisites = [
  ["AI_TEST_DATABASE_URL", Boolean(url)],
  ["test/QA database name", namedTestDb],
  ["AI_TEST_DATABASE_IDENTITY_VERIFIED=1", process.env.AI_TEST_DATABASE_IDENTITY_VERIFIED === "1"],
  ["APP_DB_PASSWORD", Boolean(process.env.APP_DB_PASSWORD)]
];
const missing = prerequisites.filter(([, ok]) => !ok).map(([name]) => name);
if (missing.length) {
  console.log(`BLOCKED: Smart Alerts PostgreSQL tests require ${missing.join(", ")}.`);
  process.exit(2);
}

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const deps = spawnSync(python, ["-c", "import pytest, psycopg2, scrapy"], { encoding: "utf8" });
if (deps.error || deps.status !== 0) {
  console.log("BLOCKED: pytest, psycopg2, and Scrapy must be installed in the selected Python environment.");
  process.exit(2);
}

console.log(`Running guarded market integration tests against verified test database '${basename(database)}'.`);
const result = spawnSync(python, ["-m", "pytest", "-q", "src/market_scraper/tests/test_market_integration_db.py"], {
  cwd: new URL("../../../ai/", import.meta.url),
  stdio: "inherit",
  shell: process.platform === "win32",
  env: process.env
});
if (result.error) {
  console.error(`Database test runner failed to start: ${result.error.message}`);
  process.exitCode = 1;
} else process.exitCode = result.status ?? 1;
