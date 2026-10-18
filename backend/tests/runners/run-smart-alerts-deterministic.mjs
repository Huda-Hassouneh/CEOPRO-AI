import { spawnSync } from "node:child_process";

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const script = "../ai/src/market_scraper/tests/run_smart_alerts_deterministic.py";
const args = process.platform === "win32" && python === "py" ? ["-3", script] : [script];
const result = spawnSync(python, args, { stdio: "inherit", shell: process.platform === "win32", env: process.env });
if (result.error) {
  console.error(`Could not start Python deterministic runner: ${result.error.message}`);
  process.exitCode = 2;
} else process.exitCode = result.status ?? 1;
