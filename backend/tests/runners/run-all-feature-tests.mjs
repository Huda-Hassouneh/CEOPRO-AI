import { spawnSync } from "node:child_process";

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const suites = [
  ["Dashboard contract", ["run", "test:dashboard:contract"]],
  ["Market Intelligence contract", ["run", "test:market-intelligence:contract"]],
  ["Demand Prediction contract", ["run", "test:demand-prediction:contract"]],
  ["Product Management contract", ["run", "test:product-management:contract"]],
  ["Competitor Management contract", ["run", "test:competitor-management:contract"]],
  ["Data Integration contract and worker contracts", ["run", "test:data-integration:contract"]],
  ["Connected Data Sources contract and quota regressions", ["run", "test:connected-data-sources:contract"]],
  ["Document Extraction contracts and regression checks", ["run", "test:document-extraction:contract"]],
  ["Document Storage contracts and regression checks", ["run", "test:document-storage:contract"]],
  ["RAG Assistant source and provider contracts", ["run", "test:rag-assistant:provider-contract"]],
  ["RAG Assistant source regressions", ["run", "test:rag-assistant:source-contract"]],
  ["Business Recommendations Node/catalog contracts", ["run", "test:business-recommendations:node-contract"]],
  ["Business Recommendations deterministic AI rule tests", ["run", "test:business-recommendations:deterministic"]],
  ["Business Recommendations Python AI/API tests", ["run", "test:business-recommendations:python"]],
  ["Smart Alerts source contracts", ["run", "test:smart-alerts:contract"]],
  ["Smart Alerts deterministic calculations and source regressions", ["run", "test:smart-alerts:deterministic"]],
  ["AI Pricing Node authorization, usage, evidence, and source contracts", ["run", "test:ai-pricing:contract"]],
  ["AI Pricing Node to Gradio request and response contract", ["run", "test:ai-pricing:gradio-contract"]],
  ["AI Pricing deterministic calculations and data-integrity regressions", ["run", "test:ai-pricing:deterministic"]],
  ["AI Pricing guarded database integration", ["run", "test:ai-pricing:database"]],
  ["Tenant Notifications regression contracts", ["run", "test:tenant-notifications"]],
  ["Platform Notifications regression contracts", ["run", "test:notifications"]],
  ["Feature Playwright E2E", ["run", "test:feature-e2e"]]
];

const failed = [];
const blocked = [];
for (const [name, args] of suites) {
  console.info(`\n=== ${name} ===`);
  const result = spawnSync(npm, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    env: process.env
  });
  const code = result.error ? 1 : (result.status ?? 1);
  if (code === 2) blocked.push(name);
  else if (code !== 0) failed.push(name);
}

console.info(`\nFeature test suites finished. Failed: ${failed.length ? failed.join(", ") : "none"}. Blocked: ${blocked.length ? blocked.join(", ") : "none"}.`);
if (failed.length) process.exitCode = 1;
