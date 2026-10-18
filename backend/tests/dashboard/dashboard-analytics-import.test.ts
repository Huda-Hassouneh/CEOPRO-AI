import assert from "node:assert/strict";
import test from "node:test";
import * as XLSX from "xlsx";
import {
  createStructuredImportTemplate,
  parseStructuredBusinessFile,
  StructuredImportError
} from "../../src/modules/dataconnection/service/structured-business-import.js";
import {
  buildSalesOverview,
  summarizeInventory
} from "../../src/modules/dashboard/helper/dashboard.helpers.js";

const PRODUCT = "123e4567-e89b-42d3-a456-426614174000";
const SECOND_PRODUCT = "123e4567-e89b-42d3-a456-426614174001";

function file(name: string, buffer: Buffer) {
  return { originalname: name, buffer, size: buffer.length };
}

function csv(name: string, body: string) {
  return file(name, Buffer.from(body, "utf8"));
}

const invoiceHeader = "invoice_number,customer_name,issue_date,due_date,subtotal,tax_amount,total_amount,currency,payment_status";
const inventoryHeader = "product_id,stock_quantity,reorder_level,safety_stock,warehouse_location";

test("a paid invoice retains its displayed number and reporting date in CSV", () => {
  const parsed = parseStructuredBusinessFile("invoices", csv("invoices.csv",
    `${invoiceHeader}\n000123,Ada,2026-09-20,2026-10-01,20.1234,1.8766,22.0000,JOD,paid\n`));
  assert.equal(parsed.kind, "invoices");
  if (parsed.kind !== "invoices") return;
  assert.equal(parsed.invoices[0]?.invoiceNumber, "000123");
  assert.equal(parsed.invoices[0]?.issueDate.toISOString(), "2026-09-20T00:00:00.000Z");
  assert.equal(parsed.invoices[0]?.totalAmount, "22.0000");
  assert.equal(parsed.invoices[0]?.paymentStatus, "PAID");

  const result = buildSalesOverview([
    { issue_date: parsed.invoices[0]!.issueDate, total_amount: parsed.invoices[0]!.totalAmount }
  ], new Date("2026-09-19T00:00:00.000Z"), 2);
  assert.deepEqual(result.points, [
    { date: "2026-09-19", value: 0 },
    { date: "2026-09-20", value: 22 }
  ]);
});

test("invoice workbook links case variant item references and verifies subtotals", () => {
  const book = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([
    invoiceHeader.split(","),
    ["INV-A", "Ada", "2026-09-20", "", "6.0000", "0", "6", "JOD", "PAID"]
  ]), "Invoices");
  XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([
    ["invoice_number", "product_id", "quantity", "unit_price"],
    ["inv-a", PRODUCT, 2, "3.0000"]
  ]), "Invoice Items");
  const content = Buffer.from(XLSX.write(book, { type: "buffer", bookType: "xlsx" }));
  const parsed = parseStructuredBusinessFile("invoices", file("invoices.xlsx", content));
  assert.equal(parsed.kind, "invoices");
  if (parsed.kind !== "invoices") return;
  assert.deepEqual(parsed.items.map(({ quantity, totalPrice }) => ({ quantity, totalPrice })), [
    { quantity: 2, totalPrice: "6.0000" }
  ]);
  assert.throws(() => parseStructuredBusinessFile("invoices", csv("bad.csv",
    `${invoiceHeader}\nINV-A,Ada,2026-09-20,,6,0,7,JOD,PAID\n`)), StructuredImportError);
});

test("inventory upload rejects duplicate balances and summarizes each product once", () => {
  const parsed = parseStructuredBusinessFile("inventory", csv("inventory.csv",
    `${inventoryHeader}\n${PRODUCT},2,5,1,East\n${PRODUCT},5,3,1,West\n${SECOND_PRODUCT},0,2,1,\n`));
  assert.equal(parsed.kind, "inventory");
  if (parsed.kind !== "inventory") return;
  const summary = summarizeInventory(parsed.inventory.map((row, i) => ({
    inventory_id: `balance-${i}`,
    product_id: row.productId,
    stock_quantity: row.stockQuantity,
    reorder_level: row.reorderLevel,
    products: { product_name: { en: `Product ${i}`, ar: "منتج" } }
  })));
  assert.equal(summary.totalItems, 2);
  assert.equal(summary.lowStock, 1);
  assert.equal(summary.outOfStock, 1);
  assert.throws(() => parseStructuredBusinessFile("inventory", csv("duplicate.csv",
    `${inventoryHeader}\n${PRODUCT},2,5,1,East\n${PRODUCT},5,3,1,east\n`)), StructuredImportError);
});

test("invalid encoding, date, product ID, workbook contents, and formulas fail before persistence", () => {
  assert.throws(() => parseStructuredBusinessFile("inventory", file("bad.csv", Buffer.from([0xff, 0xfe]))), StructuredImportError);
  assert.throws(() => parseStructuredBusinessFile("invoices", csv("date.csv",
    `${invoiceHeader}\nINV-1,,2026-02-30,,2,0,2,JOD,PAID\n`)), StructuredImportError);
  assert.throws(() => parseStructuredBusinessFile("inventory", csv("id.csv",
    `${inventoryHeader}\nunknown,1,0,0,\n`)), StructuredImportError);
  assert.throws(() => parseStructuredBusinessFile("inventory", file("bad.xlsx", Buffer.from("not an Excel file"))), StructuredImportError);
  const book = XLSX.utils.book_new();
  const sheet = XLSX.utils.aoa_to_sheet([inventoryHeader.split(","), [PRODUCT, 1, 0, 0, ""]]);
  sheet.B2 = { t: "n", f: "SUM(1,1)", v: 2 };
  XLSX.utils.book_append_sheet(book, sheet, "Inventory");
  assert.throws(() => parseStructuredBusinessFile("inventory", file("formula.xlsx", Buffer.from(XLSX.write(book, { type: "buffer", bookType: "xlsx" })))), StructuredImportError);
});

test("downloaded templates can be filled and read back", () => {
  const invoice = createStructuredImportTemplate("invoices", "xlsx");
  const workbook = XLSX.read(invoice, { type: "buffer" });
  assert.deepEqual(workbook.SheetNames, ["Invoices", "Invoice Items"]);
  const inventory = createStructuredImportTemplate("inventory", "csv");
  assert.equal(inventory.toString("utf8").trim(), "product_name,sku,stock_quantity,reorder_level,safety_stock,warehouse_location");
  const nameOnly = Buffer.from(`${inventory.toString("utf8")}Red Roses,,12,3,1,Main\r\n`);
  const parsed = parseStructuredBusinessFile("inventory", file("inventory.csv", nameOnly));
  assert.equal(parsed.kind, "inventory");
  if (parsed.kind === "inventory") assert.equal(parsed.inventory[0]?.productName, "Red Roses");
  const invoiceItems = workbook.Sheets["Invoice Items"]!;
  XLSX.utils.sheet_add_aoa(invoiceItems, [["INV-1", "Red Roses", "ROSE-01", 2, 3]], { origin: "A2" });
  const invoiceSheet = workbook.Sheets.Invoices!;
  XLSX.utils.sheet_add_aoa(invoiceSheet, [["INV-1", "Ada", "2026-09-20", "", 6, 0, 6, "JOD", "PAID"]], { origin: "A2" });
  const filled = Buffer.from(XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }));
  const parsedInvoice = parseStructuredBusinessFile("invoices", file("invoices.xlsx", filled));
  if (parsedInvoice.kind === "invoices") assert.equal(parsedInvoice.items[0]?.productName, "Red Roses");
});
