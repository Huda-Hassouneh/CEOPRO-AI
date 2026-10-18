import { test, expect } from "@playwright/test";
import { Pool } from "pg";
import * as XLSX from "xlsx";
import { randomUUID } from "node:crypto";

const enabled = process.env.STRUCTURED_IMPORT_TEST === "1";
const token = process.env.DASHBOARD_TEST_ACCESS_TOKEN;
const tenantId = process.env.DASHBOARD_TEST_TENANT_ID;
const userId = process.env.DASHBOARD_TEST_USER_ID;
const databaseUrl = process.env.DASHBOARD_TEST_DATABASE_URL;
const base = (process.env.DASHBOARD_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");

test("opt-in invoice/inventory preview creates catalog products and commits once under tenant RLS", async ({ request }) => {
  test.skip(!(enabled && token && tenantId && userId && databaseUrl),
    "Set STRUCTURED_IMPORT_TEST=1, DASHBOARD_TEST_ACCESS_TOKEN, DASHBOARD_TEST_TENANT_ID, DASHBOARD_TEST_USER_ID, and DASHBOARD_TEST_DATABASE_URL for an isolated test tenant with Product Management and extraction allowance.");

  const suffix = randomUUID().slice(0, 8);
  const sku = `E2E-${suffix}`;
  const productName = `Import test flowers ${suffix}`;
  const invoiceNumber = `E2E-INV-${suffix}`;
  const headers = { Authorization: `Bearer ${token}` };
  const inventoryFile = Buffer.from(`product_name,sku,stock_quantity,reorder_level,safety_stock,warehouse_location\n${productName},${sku},7,2,1,Main\n`);
  const preview = await request.post(`${base}/data-connection/imports/inventory/preview`, {
    headers, multipart: { file: { name: "stock.csv", mimeType: "text/csv", buffer: inventoryFile } }
  });
  expect(preview.status()).toBe(200);
  const draft = (await preview.json()).data;
  expect(draft.counts.needsAttention).toBe(1);
  const key = draft.matches[0].key;
  const choices = { [key]: { action: "create", price: "3.0000", currency: draft.primaryCurrency, sku } };
  const review = await request.post(`${base}/data-connection/imports/inventory/previews/${draft.draftId}/review`, {
    headers, data: { choices }
  });
  expect(review.status()).toBe(200);
  const reviewData = (await review.json()).data;
  expect(reviewData.changes[0].previous).toBeNull();
  const confirmPath = `${base}/data-connection/imports/inventory/previews/${draft.draftId}/confirm`;
  const confirmBody = { choices, reviewHash: reviewData.reviewHash };
  const confirmed = await request.post(confirmPath, { headers, data: confirmBody });
  expect(confirmed.status()).toBe(200);
  const result = (await confirmed.json()).data;
  expect(result.imported).toBe(1);
  const retry = await request.post(confirmPath, { headers, data: confirmBody });
  expect(retry.status()).toBe(200);
  expect((await retry.json()).data.jobId).toBe(result.jobId);

  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
    ["invoice_number", "customer_name", "issue_date", "due_date", "subtotal", "tax_amount", "total_amount", "currency", "payment_status"],
    [invoiceNumber, "E2E Customer", "2026-10-12", "", "6.0000", "0.0000", "6.0000", draft.primaryCurrency, "PAID"]
  ]), "Invoices");
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
    ["invoice_number", "product_name", "sku", "quantity", "unit_price"],
    [invoiceNumber, productName, sku, 2, "3.0000"]
  ]), "Invoice Items");
  const invoiceFile = Buffer.from(XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }));
  const invoicePreviewResponse = await request.post(`${base}/data-connection/imports/invoices/preview`, {
    headers, multipart: { file: { name: "invoices.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: invoiceFile } }
  });
  expect(invoicePreviewResponse.status()).toBe(200);
  const invoicePreview = (await invoicePreviewResponse.json()).data;
  expect(invoicePreview.counts.matched).toBe(1);
  const invoiceReview = await request.post(`${base}/data-connection/imports/invoices/previews/${invoicePreview.draftId}/review`, {
    headers, data: { choices: {} }
  });
  expect(invoiceReview.status()).toBe(200);
  const invoiceResult = await request.post(`${base}/data-connection/imports/invoices/previews/${invoicePreview.draftId}/confirm`, {
    headers, data: { choices: {}, reviewHash: (await invoiceReview.json()).data.reviewHash }
  });
  expect(invoiceResult.status()).toBe(200);
  expect((await invoiceResult.json()).data.invoiceItems).toBe(1);

  const pool = new Pool({ connectionString: databaseUrl });
  const client = await pool.connect();
  try {
    await client.query("BEGIN READ ONLY");
    await client.query("SELECT set_config('app.current_tenant_id', $1, true), set_config('app.current_user_id', $2, true)", [tenantId, userId]);
    const product = await client.query("SELECT product_id FROM products WHERE tenant_id=$1 AND sku=$2 AND deleted_at IS NULL", [tenantId, sku]);
    expect(product.rowCount).toBe(1);
    const stock = await client.query("SELECT stock_quantity FROM inventory WHERE tenant_id=$1 AND product_id=$2 AND warehouse_location='Main'", [tenantId, product.rows[0].product_id]);
    expect(stock.rows).toHaveLength(1);
    expect(stock.rows[0].stock_quantity).toBe(7);
    const items = await client.query("SELECT ii.quantity FROM invoices i JOIN invoice_items ii ON ii.tenant_id=i.tenant_id AND ii.invoice_id=i.invoice_id WHERE i.tenant_id=$1 AND i.invoice_number=$2 AND ii.product_id=$3", [tenantId, invoiceNumber, product.rows[0].product_id]);
    expect(items.rows).toHaveLength(1);
    expect(items.rows[0].quantity).toBe(2);
    await client.query("COMMIT");
  } finally {
    await client.query("ROLLBACK").catch(() => undefined);
    client.release();
    await pool.end();
  }
});
