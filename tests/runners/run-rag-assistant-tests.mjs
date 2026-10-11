import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["RAG Assistant source and regression contracts", ["run", "test:rag-assistant:source-contract"]],
  ["RAG Assistant controlled Gradio request/response contract", ["run", "test:rag-assistant:provider-contract"]],
  ["AI-team RAG retrieval and generation unit tests", ["run", "test:rag-assistant:ai-unit"]],
  ["RAG Assistant deterministic Playwright diagnostics", ["run", "test:rag-assistant:e2e"]]
];
const failed = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const result = spawnSync(npm, args, { stdio: "inherit", shell: process.platform === "win32", env: process.env });
  if (result.error || result.status !== 0) failed.push(name);
}
console.info(`\nRAG Assistant suites finished. Failed suites: ${failed.length ? failed.join(", ") : "none"}.`);
if (failed.length) process.exitCode = 1;
