import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["AI deterministic rule and calculation tests", ["run", "test:business-recommendations:deterministic"]],
  ["Node catalog, plan, and architecture contracts", ["run", "test:business-recommendations:node-contract"]],
  ["Python AI rules and endpoint unit tests", ["run", "test:business-recommendations:python"]],
  ["AI PostgreSQL signal and RLS integration tests", ["run", "test:business-recommendations:ai-db"]],
  ["Frontend/API and opt-in live AI diagnostics", ["run", "test:business-recommendations:frontend"]]
];
const results = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const run = spawnSync(npm, args, {
    encoding: "utf8", shell: process.platform === "win32", env: process.env
  });
  if (run.stdout) process.stdout.write(run.stdout);
  if (run.stderr) process.stderr.write(run.stderr);
  const log = `${run.stdout || ""}\n${run.stderr || ""}`;
  // Work Mode can reject nested child processes with EPERM while leaving a
  // misleading numeric status. Treat that run as blocked unless output proves
  // a real test result. Direct npm invocations remain the source of truth.
  const nestedProcessBlocked = Boolean(run.error && /EPERM/.test(run.error.message || ""));
  let status = run.status === null ? "ERROR" : nestedProcessBlocked ? "BLOCKED" : run.status === 2 && /\[BLOCKED\]/.test(log) ? "BLOCKED" : run.status !== 0 ? "FAIL" : /\[BLOCKED\]|\d+ skipped/.test(log) ? "BLOCKED" : "PASS";
  results.push({ name, status, exitCode: run.status, error: run.status === null || nestedProcessBlocked ? run.error?.message || "nested subprocess was blocked by the execution environment" : null });
}
const summary = {
  generatedAt: new Date().toISOString(),
  suite: "Business Recommendations",
  summary: Object.fromEntries(["PASS", "FAIL", "SKIP", "BLOCKED", "ERROR"].map((state) => [state, results.filter((row) => row.status === state).length])),
  tests: results
};
mkdirSync("tests/reports/business-recommendations", { recursive: true });
writeFileSync("tests/reports/business-recommendations/run-summary.json", JSON.stringify(summary, null, 2));
console.info(`\nBusiness Recommendations status: ${JSON.stringify(summary.summary)}`);
if (results.some((row) => row.status === "FAIL" || row.status === "ERROR")) process.exitCode = 1;
else if (results.some((row) => row.status === "BLOCKED")) process.exitCode = 2;
