import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const python = process.platform === "win32" ? "python" : "python3";
const mode = process.argv[2] || "unit";
const aiRoot = resolve(process.cwd(), "../ai");
const files = mode === "database" || mode === "tenant"
  ? [
      "src/ai/tests/test_insights_pipeline_integration_db.py",
      "src/ai/tests/test_dashboard_recommendations_integration_db.py"
    ]
  : [
      "src/ai/tests/test_insights_cross_signal.py",
      "src/ai/tests/test_insights_causal_chain.py",
      "src/ai/tests/test_business_recommendations_audit.py",
      "src/ai/tests/test_main.py"
    ];
const check = spawnSync(python, ["-m", "pytest", "--version"], {
  cwd: aiRoot, encoding: "utf8", shell: process.platform === "win32", env: process.env
});
if (check.error || check.status !== 0) {
  console.error(`[BLOCKED] Python ${mode} suite: pytest is not installed in the selected Python environment.`);
  process.exitCode = 2;
} else {
  const args = ["-m", "pytest", "-q", ...files];
  if (mode === "tenant") args.push("-k", "rls_context_prevents_pipeline");
  const result = spawnSync(python, args, {
    cwd: aiRoot, stdio: "inherit", shell: process.platform === "win32", env: process.env
  });
  if (result.error) console.error(`Python ${mode} suite unavailable: ${result.error.message}`);
  if (result.error || result.status !== 0) process.exitCode = result.status || 1;
}
