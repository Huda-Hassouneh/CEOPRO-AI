import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const python = process.platform === "win32" ? "python" : "python3";
const aiRoot = resolve(process.cwd(), "../ai");
const result = spawnSync(python, ["src/ai/tests/run_business_recommendations_deterministic.py"], {
  cwd: aiRoot,
  stdio: "inherit",
  shell: process.platform === "win32",
  env: process.env
});
if (result.error) console.error(`Deterministic Business Recommendations tests unavailable: ${result.error.message}`);
if (result.error || result.status !== 0) process.exitCode = result.status || 1;
