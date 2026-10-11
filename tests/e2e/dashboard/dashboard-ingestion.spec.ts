import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import { basename } from "node:path";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const enabled = process.env.DASHBOARD_TEST_LIVE_INGESTION === "1";
const token = process.env.DASHBOARD_TEST_ACCESS_TOKEN;
const tenantId = process.env.DASHBOARD_TEST_TENANT_ID;
const userId = process.env.DASHBOARD_TEST_USER_ID;
const filePath = process.env.DASHBOARD_TEST_INGESTION_FILE;
const apiBaseUrl = (process.env.DASHBOARD_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const dbUrl = process.env.DASHBOARD_TEST_DATABASE_URL;
if (!(enabled && token && tenantId && userId && filePath && dbUrl)) test.skip(true, "BLOCKED: live extraction, a valid test token/database/file, entitlement, and worker are not configured.");

test("live Data Connections upload is staged, processed, and visible in DB diagnostics", async ({}, testInfo) => {
  testInfo.skip(!(enabled && token && tenantId && userId && filePath && dbUrl), "BLOCKED: live ingestion requires DASHBOARD_TEST_LIVE_INGESTION=1, auth variables, a test database, a real valid sales file, reachable CEOPRO/AI services, extraction entitlement, and a running ingestion worker.");
  testInfo.annotations.push({ type: "mode", description: "live-ai-ingestion" });
  testInfo.annotations.push({ type: "upstream-service", description: "analytics Gradio extract_file + CEOPRO data-ingestion worker" });
  const file = await fs.readFile(filePath!);
  const form = new FormData();
  form.append("file", new Blob([file]), basename(filePath!));
  const response = await fetch(`${apiBaseUrl}/data-connection`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
  const responseBody = await response.json().catch(() => null);
  expect(response.status, `Real ingestion endpoint returned HTTP ${response.status}; response content omitted to avoid disclosing uploaded row data.`).toBe(200);
  const jobId = responseBody?.data?.job_id;
  expect(jobId, "Successful extraction response did not include its CEOPRO job ID").toMatch(/^[0-9a-f-]{36}$/i);
  testInfo.annotations.push({ type: "ingestion-job", description: jobId });
  testInfo.annotations.push({ type: "staged-rows", description: String(responseBody.data.staged_row_count) });

  const db = new DashboardDatabase(dbUrl!);
  try {
    const deadline = Date.now() + 5 * 60_000;
    let snapshot = await db.getIngestionSnapshot(tenantId!, userId!, jobId);
    while (snapshot && !["COMPLETED", "FAILED", "PARTIAL", "COMPLETED_WITH_ERRORS"].includes(snapshot.status) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 3_000));
      snapshot = await db.getIngestionSnapshot(tenantId!, userId!, jobId);
    }
    expect(snapshot, "The upload response's job could not be read back under the authenticated tenant RLS context").not.toBeNull();
    testInfo.annotations.push({ type: "ingestion-snapshot", description: JSON.stringify(snapshot) });
    expect(Date.now(), "Ingestion job did not reach a terminal state before the five-minute deadline").toBeLessThan(deadline);
    expect(snapshot!.status).toBe("COMPLETED");
    expect(snapshot!.stagingPending, "Rows remained pending after the job completed").toBe(0);
    expect(snapshot!.stagingTotal).toBeGreaterThan(0);
  } finally { await db.close(); }
});
