import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["Document Extraction validator, AI, staging, worker, and source regression contracts", ["run", "test:document-extraction:contract"]],
  ["Document Extraction real UI/API/database/worker scenarios", ["run", "test:document-extraction:e2e"]]
];
const failed = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const result = spawnSync(npm, args, { stdio: "inherit", shell: process.platform === "win32", env: process.env });
  if (result.error || result.status !== 0) failed.push(name);
}
console.info(`\nDocument Extraction suite finished. Failed suites: ${failed.length ? failed.join(", ") : "none"}.`);
if (failed.length) process.exitCode = 1;
