import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["Node architecture and contract checks", "test:smart-alerts:contract"],
  ["AI deterministic calculations and regressions", "test:smart-alerts:deterministic"],
  ["Guarded PostgreSQL integration and RLS", "test:smart-alerts:database"],
  ["Customer-flow Playwright diagnostics", "test:smart-alerts:e2e"]
];
const results = [];
for (const [name, script] of suites) {
  console.log(`\n=== ${name} ===`);
  const result = spawnSync(npm, ["run", script], {
    stdio: "inherit", shell: process.platform === "win32", env: process.env
  });
  const code = result.error ? 1 : (result.status ?? 1);
  results.push({ name, script, status: code === 0 ? "PASS" : code === 2 ? "BLOCKED" : "FAIL", exitCode: code });
}
console.log("\nSmart Alerts suite summary:");
for (const row of results) console.log(`${row.status.padEnd(7)} ${row.name}`);
process.exitCode = results.some(row => row.status === "FAIL") ? 1 : 0;
