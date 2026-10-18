import { extname } from "node:path";
import * as XLSX from "xlsx";
import { MAX_UPLOAD_SIZE_BYTES } from "../types/dataconnection.validation.js";

export type StructuredImportKind = "invoices" | "inventory";
export type ImportIssue = { sheet: string; row: number; message: string };
export type InvoiceImportRow = {
  sheet: string;
  row: number;
  invoiceNumber: string;
  customerName: string | null;
  issueDate: Date;
  dueDate: Date | null;
  subtotal: string;
  taxAmount: string;
  totalAmount: string;
  currency: string;
  paymentStatus: string;
};
export type InvoiceItemImportRow = {
  sheet: string;
  row: number;
  invoiceNumber: string;
  productId: string;
  productName: string;
  sku: string;
  referenceKey: string;
  quantity: number;
  unitPrice: string;
  totalPrice: string;
};
export type InventoryImportRow = {
  sheet: string;
  row: number;
  productId: string;
  productName: string;
  sku: string;
  referenceKey: string;
  stockQuantity: number;
  reorderLevel: number;
  safetyStock: number;
  warehouseLocation: string | null;
};
export type ParsedBusinessImport =
  | { kind: "invoices"; invoices: InvoiceImportRow[]; items: InvoiceItemImportRow[] }
  | { kind: "inventory"; inventory: InventoryImportRow[] };

const INVOICE_HEADERS = ["invoice_number", "customer_name", "issue_date", "due_date", "subtotal", "tax_amount", "total_amount", "currency", "payment_status"];
const ITEM_HEADERS = ["invoice_number", "product_id", "product_name", "sku", "quantity", "unit_price"];
const INVENTORY_HEADERS = ["product_id", "product_name", "sku", "stock_quantity", "reorder_level", "safety_stock", "warehouse_location"];
const ITEM_REQUIRED = ["invoice_number", "quantity", "unit_price"];
const INVENTORY_REQUIRED = ["stock_quantity", "reorder_level", "safety_stock"];
const MAX_ROWS = 1_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PAYMENT_STATUSES = new Set(["UNPAID", "PAID", "PARTIAL", "OVERDUE", "CANCELLED"]);

export class StructuredImportError extends Error {
  constructor(message: string, readonly issues: ImportIssue[] = []) {
    super(message);
    this.name = "StructuredImportError";
  }
}

function text(value: unknown): string {
  return value == null ? "" : String(value).trim();
}

function date(value: unknown, sheet: string, row: number, field: string): Date | null {
  if (value === "" || value == null) return null;
  const input = value instanceof Date && !Number.isNaN(value.getTime())
    ? value.toISOString().slice(0, 10)
    : text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input)) {
    throw new StructuredImportError(`${field} must use YYYY-MM-DD.`, [{ sheet, row, message: `${field} must use YYYY-MM-DD.` }]);
  }
  const result = new Date(`${input}T00:00:00.000Z`);
  if (Number.isNaN(result.getTime()) || result.toISOString().slice(0, 10) !== input) {
    throw new StructuredImportError(`${field} is not a real calendar date.`, [{ sheet, row, message: `${field} is not a real calendar date.` }]);
  }
  return result;
}

function money(value: unknown, sheet: string, row: number, field: string): { scaled: number; decimal: string } {
  const input = text(value);
  if (!/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/.test(input)) {
    throw new StructuredImportError(`${field} must be a nonnegative amount with at most four decimal places.`, [{ sheet, row, message: `${field} must be a nonnegative amount with at most four decimal places.` }]);
  }
  const [wholePart, fraction = ""] = input.split(".");
  const decimal = `${wholePart}.${fraction.padEnd(4, "0")}`;
  return { scaled: Number(wholePart) * 10_000 + Number(fraction.padEnd(4, "0")), decimal };
}

function whole(value: unknown, sheet: string, row: number, field: string, min = 0): number {
  const input = text(value);
  const number = Number(input);
  if (!/^\d+$/.test(input) || !Number.isInteger(number) || number < min || number > 2_147_483_647) {
    throw new StructuredImportError(`${field} must be an integer of at least ${min}.`, [{ sheet, row, message: `${field} must be an integer of at least ${min}.` }]);
  }
  return number;
}

function identifier(value: unknown, sheet: string, row: number): string {
  const id = text(value).toLowerCase();
  if (id && !UUID.test(id)) {
    throw new StructuredImportError("product_id must be an existing product UUID.", [{ sheet, row, message: "product_id must be an existing product UUID." }]);
  }
  return id;
}

export function normalizeProductReference(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLocaleLowerCase("und");
}

function productReference(values: Record<string, unknown>, sheet: string, row: number) {
  const productId = identifier(values.product_id, sheet, row);
  const productName = text(values.product_name);
  const sku = text(values.sku);
  if (!productId && !productName && !sku) {
    throw new StructuredImportError("Enter a product_name, sku, or legacy product_id.", [{ sheet, row, message: "Enter a product_name, sku, or legacy product_id." }]);
  }
  if (productName.length > 255 || sku.length > 100) {
    throw new StructuredImportError("Product name or SKU is too long.", [{ sheet, row, message: "Product name or SKU is too long." }]);
  }
  if (sku && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(sku)) {
    throw new StructuredImportError("sku may contain letters, numbers, dots, underscores, and hyphens.", [{ sheet, row, message: "Invalid SKU format." }]);
  }
  const referenceKey = productId ? `id:${productId}` : sku ? `sku:${normalizeProductReference(sku)}` : `name:${normalizeProductReference(productName)}`;
  return { sheet, row, productId, productName, sku, referenceKey };
}

function rows(workbook: XLSX.WorkBook, sheetName: string, allowed: string[], required: string[], allowEmpty = false) {
  const sheet = workbook.Sheets[sheetName];
  if (!sheet) throw new StructuredImportError(`Missing ${sheetName} worksheet.`);
  const range = XLSX.utils.decode_range(sheet["!ref"] ?? "A1");
  if (range.e.r > MAX_ROWS || range.e.c >= 32) {
    throw new StructuredImportError(`${sheetName} exceeds ${MAX_ROWS} data rows or 32 columns.`);
  }
  for (let row = range.s.r; row <= range.e.r; row += 1) {
    for (let column = range.s.c; column <= range.e.c; column += 1) {
      const cell = Array.isArray(sheet)
        ? (sheet[row] as XLSX.CellObject[] | undefined)?.[column]
        : sheet[XLSX.utils.encode_cell({ r: row, c: column })];
      if (cell && ("f" in cell || "F" in cell)) {
        throw new StructuredImportError("Spreadsheet formulas are not allowed in import files.", [{ sheet: sheetName, row: row + 1, message: "Spreadsheet formulas are not allowed in import files." }]);
      }
    }
  }
  const matrix = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, raw: true, defval: "", blankrows: true }) as unknown[][];
  const headers = (matrix[0] ?? []).map((value) => text(value).replace(/^\uFEFF/, "").toLowerCase());
  if (new Set(headers).size !== headers.length || headers.some((header) => !allowed.includes(header)) || required.some((header) => !headers.includes(header))) {
    throw new StructuredImportError(`${sheetName} columns must match the published template. Required: ${required.join(", ")}.`);
  }
  const records = matrix.slice(1).flatMap((values, index) => {
    if (!values.some((value) => text(value) !== "")) return [];
    return [{ row: index + 2, values: Object.fromEntries(headers.map((header, i) => [header, values[i] ?? ""])) }];
  });
  if (records.length === 0 && !allowEmpty) throw new StructuredImportError(`${sheetName} contains no data rows.`);
  return records;
}

export function parseStructuredBusinessFile(kind: StructuredImportKind, file: { originalname: string; size: number; buffer: Buffer }): ParsedBusinessImport {
  const extension = extname(file.originalname).toLowerCase();
  if (!Buffer.isBuffer(file.buffer) || file.size !== file.buffer.length || file.size <= 0 || file.size > MAX_UPLOAD_SIZE_BYTES || ![".csv", ".xlsx"].includes(extension)) {
    throw new StructuredImportError("Upload a nonempty CSV or XLSX file within the configured file-size limit.");
  }
  if (extension === ".xlsx" && file.buffer.subarray(0, 2).toString("ascii") !== "PK") {
    throw new StructuredImportError("The XLSX file content does not match its extension.");
  }
  if (extension === ".csv") {
    try {
      if (file.buffer.includes(0)) throw new Error("NUL byte");
      new TextDecoder("utf-8", { fatal: true }).decode(file.buffer);
    } catch {
      throw new StructuredImportError("The CSV file must contain valid UTF-8 text.");
    }
  }
  let workbook: XLSX.WorkBook;
  try {
    workbook = extension === ".csv"
      ? XLSX.read(new TextDecoder("utf-8", { fatal: true }).decode(file.buffer), { type: "string", cellDates: true, dense: true, raw: true })
      : XLSX.read(file.buffer, { type: "buffer", cellDates: true, dense: true });
  } catch {
    throw new StructuredImportError("The uploaded spreadsheet could not be read.");
  }
  if (extension === ".xlsx" && workbook.SheetNames.length > 2) {
    throw new StructuredImportError("The workbook contains unexpected worksheets.");
  }
  if (kind === "inventory") {
    const sheet = extension === ".csv" ? workbook.SheetNames[0]! : "Inventory";
    if (extension === ".xlsx" && (workbook.SheetNames.length !== 1 || !workbook.Sheets.Inventory)) {
      throw new StructuredImportError("Use the Inventory worksheet from the published template.");
    }
    const seen = new Set<string>();
    const inventory = rows(workbook, sheet, INVENTORY_HEADERS, INVENTORY_REQUIRED).map(({ row, values }) => {
      const reference = productReference(values, sheet, row);
      const warehouseLocation = text(values.warehouse_location) || null;
      if (warehouseLocation && warehouseLocation.length > 150) throw new StructuredImportError("warehouse_location exceeds 150 characters.", [{ sheet, row, message: "warehouse_location exceeds 150 characters." }]);
      const key = `${reference.referenceKey}:${normalizeProductReference(warehouseLocation ?? "")}`;
      if (seen.has(key)) throw new StructuredImportError("Duplicate product and warehouse in this file.", [{ sheet, row, message: "Duplicate product and warehouse in this file." }]);
      seen.add(key);
      return {
        ...reference,
        stockQuantity: whole(values.stock_quantity, sheet, row, "stock_quantity"),
        reorderLevel: whole(values.reorder_level, sheet, row, "reorder_level"),
        safetyStock: whole(values.safety_stock, sheet, row, "safety_stock"),
        warehouseLocation
      };
    });
    return { kind, inventory };
  }
  const invoiceSheet = extension === ".csv" ? workbook.SheetNames[0]! : "Invoices";
  if (extension === ".xlsx" && (!workbook.Sheets.Invoices || workbook.SheetNames.some((name) => !["Invoices", "Invoice Items"].includes(name)))) {
    throw new StructuredImportError("Use the Invoices and optional Invoice Items worksheets from the published template.");
  }
  const seen = new Set<string>();
  const invoices = rows(workbook, invoiceSheet, INVOICE_HEADERS, ["invoice_number", "issue_date", "subtotal", "tax_amount", "total_amount", "currency", "payment_status"]).map(({ row, values }) => {
    const invoiceNumber = text(values.invoice_number);
    if (!invoiceNumber || invoiceNumber.length > 100 || seen.has(invoiceNumber.toLowerCase())) {
      throw new StructuredImportError("invoice_number is missing, too long, or duplicated in this file.", [{ sheet: invoiceSheet, row, message: "invoice_number is missing, too long, or duplicated in this file." }]);
    }
    seen.add(invoiceNumber.toLowerCase());
    const customerName = text(values.customer_name) || null;
    if (customerName && customerName.length > 255) throw new StructuredImportError("customer_name exceeds 255 characters.", [{ sheet: invoiceSheet, row, message: "customer_name exceeds 255 characters." }]);
    const issueDate = date(values.issue_date, invoiceSheet, row, "issue_date");
    if (!issueDate) throw new StructuredImportError("issue_date is required.", [{ sheet: invoiceSheet, row, message: "issue_date is required." }]);
    const dueDate = date(values.due_date, invoiceSheet, row, "due_date");
    if (dueDate && dueDate < issueDate) throw new StructuredImportError("due_date cannot precede issue_date.", [{ sheet: invoiceSheet, row, message: "due_date cannot precede issue_date." }]);
    const subtotal = money(values.subtotal, invoiceSheet, row, "subtotal");
    const taxAmount = money(values.tax_amount, invoiceSheet, row, "tax_amount");
    const totalAmount = money(values.total_amount, invoiceSheet, row, "total_amount");
    if (subtotal.scaled + taxAmount.scaled !== totalAmount.scaled) throw new StructuredImportError("total_amount must equal subtotal plus tax_amount.", [{ sheet: invoiceSheet, row, message: "total_amount must equal subtotal plus tax_amount." }]);
    const currency = text(values.currency).toUpperCase();
    if (!/^[A-Z]{3}$/.test(currency)) throw new StructuredImportError("currency must be a three-letter code.", [{ sheet: invoiceSheet, row, message: "currency must be a three-letter code." }]);
    const paymentStatus = text(values.payment_status).toUpperCase();
    if (!PAYMENT_STATUSES.has(paymentStatus)) throw new StructuredImportError("Invalid payment_status.", [{ sheet: invoiceSheet, row, message: "Invalid payment_status." }]);
    return { sheet: invoiceSheet, row, invoiceNumber, customerName, issueDate, dueDate, subtotal: subtotal.decimal, taxAmount: taxAmount.decimal, totalAmount: totalAmount.decimal, currency, paymentStatus };
  });
  const items: InvoiceItemImportRow[] = [];
  if (workbook.Sheets["Invoice Items"]) {
    const sheet = "Invoice Items";
    const itemRows = rows(workbook, sheet, ITEM_HEADERS, ITEM_REQUIRED, true);
    const seenItems = new Set<string>();
    for (const { row, values } of itemRows) {
      const invoiceNumber = text(values.invoice_number);
      const reference = productReference(values, sheet, row);
      if (!seen.has(invoiceNumber.toLowerCase())) throw new StructuredImportError("Invoice Items refers to an invoice outside this file.", [{ sheet, row, message: "Invoice Items refers to an invoice outside this file." }]);
      const key = `${invoiceNumber.toLowerCase()}:${reference.referenceKey}`;
      if (seenItems.has(key)) throw new StructuredImportError("Duplicate product line for this invoice.", [{ sheet, row, message: "Duplicate product line for this invoice." }]);
      seenItems.add(key);
      const quantity = whole(values.quantity, sheet, row, "quantity", 1);
      const unitPrice = money(values.unit_price, sheet, row, "unit_price");
      if (quantity > Math.floor(999_999_999_999 / Math.max(1, unitPrice.scaled))) {
        throw new StructuredImportError("Line total exceeds the supported amount.", [{ sheet, row, message: "Line total exceeds the supported amount." }]);
      }
      const totalScaled = quantity * unitPrice.scaled;
      const totalPrice = `${Math.floor(totalScaled / 10_000)}.${String(totalScaled % 10_000).padStart(4, "0")}`;
      items.push({ ...reference, invoiceNumber, quantity, unitPrice: unitPrice.decimal, totalPrice });
    }
    if (items.length > 0) {
      for (const invoice of invoices) {
        const lines = items.filter((item) => item.invoiceNumber.toLowerCase() === invoice.invoiceNumber.toLowerCase());
        const lineSubtotal = lines.reduce((sum, item) => sum + Number(item.totalPrice.replace(".", "")), 0);
        if (!lines.length || lineSubtotal !== Number(invoice.subtotal.replace(".", ""))) {
          const message = `Invoice ${invoice.invoiceNumber} item totals must equal its subtotal.`;
          throw new StructuredImportError(message, [{ sheet: invoice.sheet, row: invoice.row, message }]);
        }
      }
    }
  }
  return { kind, invoices, items };
}

export function createStructuredImportTemplate(kind: StructuredImportKind, format: "csv" | "xlsx"): Buffer {
  const headers = kind === "invoices" ? INVOICE_HEADERS : INVENTORY_HEADERS.filter((value) => value !== "product_id");
  if (format === "csv") return Buffer.from(`${headers.join(",")}\r\n`, "utf8");
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([headers]), kind === "invoices" ? "Invoices" : "Inventory");
  if (kind === "invoices") XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([ITEM_HEADERS.filter((value) => value !== "product_id")]), "Invoice Items");
  return Buffer.from(XLSX.write(workbook, { type: "buffer", bookType: "xlsx" }));
}
