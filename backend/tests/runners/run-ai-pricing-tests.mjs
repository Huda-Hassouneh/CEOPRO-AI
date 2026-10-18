import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const reportDir = resolve("tests/reports/ai-pricing");
mkdirSync(reportDir, { recursive: true });
const suites = [
  ["Node entitlement, usage, persistence, and architecture regressions", "test:ai-pricing:contract"],
  ["Node to Gradio request and response contract", "test:ai-pricing:gradio-contract"],
  ["Python pricing calculations and source regressions", "test:ai-pricing:deterministic"],
  ["Guarded Python PostgreSQL pricing integration and RLS", "test:ai-pricing:database"],
  ["Authenticated pricing frontend and localization diagnostics", "test:ai-pricing:frontend"],
  ["Opt-in customer frontend to Node to hosted Gradio E2E", "test:ai-pricing:live-gradio"]
];
const results = [];
for (const [name, script] of suites) {
  console.log(`\n=== ${name} ===`);
  const result = spawnSync(npm, ["run", script], { stdio: "inherit", shell: process.platform === "win32", env: process.env });
  const code = result.error ? 1 : (result.status ?? 1);
  let status = code === 0 ? "PASS" : code === 2 ? "BLOCKED" : "FAIL";
  if (script.startsWith("test:ai-pricing:") && /e2e|frontend|live-gradio/.test(script) && code === 0) {
    try {
      const diagnostics = JSON.parse(readFileSync(resolve(reportDir, "diagnostics.json"), "utf8"));
      if (diagnostics.summary?.BLOCKED > 0 && diagnostics.summary?.PASS === 0) status = "BLOCKED";
    } catch { /* A missing diagnostics report is not evidence of a blocked pass. */ }
  }
  results.push({ name, script, status, exitCode: code });
}
const summary = { generatedAt: new Date().toISOString(), suite: "Feature 15 AI Pricing", tests: results,
  counts: Object.fromEntries(["PASS", "FAIL", "BLOCKED"].map(status => [status, results.filter(row => row.status === status).length])) };
writeFileSync(resolve(reportDir, "runner-summary.json"), JSON.stringify(summary, null, 2));
console.log("\nAI Pricing suite summary:");
for (const row of results) console.log(`[${row.status}] ${row.name}`);
process.exitCode = results.some(row => row.status === "FAIL") ? 1 : 0;
