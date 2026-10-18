import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["Connected Data Sources contract and known-gap regressions", ["run", "test:connected-data-sources:contract"]],
  ["Connected Data Sources real API/UI/database E2E", ["run", "test:connected-data-sources:e2e"]]
];

const failed = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const result = spawnSync(npm, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    env: process.env
  });
  if (result.error || result.status !== 0) failed.push(name);
}

console.info(`\nConnected Data Sources tests finished. Failed suites: ${failed.length ? failed.join(", ") : "none"}.`);
if (failed.length) process.exitCode = 1;
