import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const mode = process.argv[2] || "deterministic";
const python = process.platform === "win32" ? "python" : "python3";
const aiRoot = resolve(process.cwd(), "../ai");
const invoke = (args) => spawnSync(python, args, {
  cwd: aiRoot, encoding: "utf8", stdio: "inherit", shell: process.platform === "win32", env: process.env
});

if (mode === "deterministic") {
  const reportPath = resolve(process.cwd(), "tests/reports/ai-pricing/python-deterministic-results.json");
  const result = invoke(["-m", "src.ai.tests.run_pricing_feature15_qa", reportPath]);
  if (result.error) console.error(`[BLOCKED] Python deterministic suite unavailable: ${result.error.message}`);
  process.exitCode = result.error ? 2 : (result.status ?? 1);
} else if (mode === "database" || mode === "fastapi") {
  const url = process.env.AI_TEST_DATABASE_URL || "";
  const name = (() => { try { return new URL(url).pathname.split("/").filter(Boolean).at(-1) || ""; } catch { return ""; } })();
  const safeName = /(^|[-_])(test|testing|qa|e2e)([-_]|$)/i.test(name);
  if (!safeName || process.env.AI_TEST_DATABASE_IDENTITY_VERIFIED !== "1") {
    console.error("[BLOCKED] Set AI_TEST_DATABASE_URL to a dedicated test/QA database and set AI_TEST_DATABASE_IDENTITY_VERIFIED=1 only after verifying its service identity.");
    process.exitCode = 2;
  } else if (mode === "fastapi" && process.env.AI_PRICING_FASTAPI_TESTS !== "1") {
    console.error("[BLOCKED] FastAPI integration is opt-in. Set AI_PRICING_FASTAPI_TESTS=1 for a dedicated test tenant/database.");
    process.exitCode = 2;
  } else {
    const check = spawnSync(python, ["-m", "pytest", "--version"], { cwd: aiRoot, encoding: "utf8", shell: process.platform === "win32", env: process.env });
    if (check.error || check.status !== 0) {
      console.error("[BLOCKED] pytest is not installed in the selected Python environment.");
      process.exitCode = 2;
    } else {
      const files = mode === "database"
        ? ["src/ai/tests/test_pricing_integration_db.py"]
        : ["src/ai/tests/test_pricing_integration_db.py", "src/ai/tests/test_main.py"];
      const result = invoke(["-m", "pytest", "-q", ...files]);
      if (result.error) console.error(`[BLOCKED] Python ${mode} suite unavailable: ${result.error.message}`);
      process.exitCode = result.error ? 2 : (result.status ?? 1);
    }
  }
} else {
  console.error(`Unknown AI Pricing Python mode: ${mode}`);
  process.exitCode = 2;
}
