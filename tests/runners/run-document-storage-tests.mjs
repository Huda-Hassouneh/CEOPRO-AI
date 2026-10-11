import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["Document Storage source contracts and regression checks", ["run", "test:document-storage:contract"]],
  ["Document Storage database/API/MinIO E2E diagnostics", ["run", "test:document-storage:e2e"]]
];
const failed = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const result = spawnSync(npm, args, { stdio: "inherit", shell: process.platform === "win32", env: process.env });
  if (result.error || result.status !== 0) failed.push(name);
}
console.info(`\nDocument Storage suite finished. Failed suites: ${failed.length ? failed.join(", ") : "none"}.`);
if (failed.length) process.exitCode = 1;
