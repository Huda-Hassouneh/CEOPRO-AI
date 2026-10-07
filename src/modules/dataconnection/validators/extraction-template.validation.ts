import * as xlsx from "xlsx";

/**
 * Mirrors the extraction service's deterministic header matcher.
 * Keep these canonical fields and aliases in sync with
 * extraction/template_detection.py and template_contract.py.
 */
export const REQUIRED_RECOGNIZED_FIELDS = [
  "product_name",
  "quantity",
  "unit_price"
] as const;

export const REQUIRED_CANONICAL_TEMPLATE_FIELDS = [
  "product_name",
  "quantity",
  "unit_price",
  "currency",
  "transaction_date"
] as const;

const CANONICAL_FIELDS = [
  ...REQUIRED_CANONICAL_TEMPLATE_FIELDS,
  "discount_pct",
  "invoice_id",
  "order_id",
  "email",
  "phone",
  "competitor_name",
  "amount_raw"
] as const;

const HEADER_SYNONYMS: Record<string, readonly string[]> = {
  amount_raw: [
    "amount", "amount raw", "total", "grand total", "total_ttc", "net amount",
    "total price", "المبلغ", "الإجمالي"
  ],
  unit_price: [
    "unit price", "price", "unitprice", "prix_unitaire", "prix unitaire",
    "سعر الوحدة", "السعر"
  ],
  quantity: ["quantity", "qty", "qty.", "qte", "الكمية", "الكميه", "كمية"],
  discount_pct: ["discount", "discount %", "discount_pct", "خصم", "نسبة الخصم"],
  transaction_date: [
    "date", "transaction date", "invoice date", "date time", "datetime",
    "التاريخ", "تاريخ"
  ],
  email: ["email", "e-mail", "email address", "البريد الإلكتروني"],
  phone: ["phone", "phone number", "mobile", "الهاتف", "رقم الهاتف"],
  product_name: ["product", "product name", "item", "item name", "اسم المنتج", "المنتج"],
  competitor_name: ["competitor", "competitor name", "المنافس"],
  invoice_id: [
    "invoice", "invoice id", "invoice number", "invoice no", "num_facture",
    "رقم الفاتورة"
  ],
  order_id: ["order", "order id", "order number", "order no", "رقم الطلب"]
};

const RECOGNIZED_MODE_MIN_COVERAGE = 0.5;

export type ExtractionTemplateMode = "TEMPLATE_COMPLIANT" | "RECOGNIZED" | "FALLBACK";

export type HeaderAssessment = {
  mode: ExtractionTemplateMode;
  coverageRatio: number;
  mappedFields: Set<string>;
  headerMapping: Record<string, string>;
  unmappedHeaders: string[];
};

export function normalizeExtractionHeader(header: string): string {
  return header.trim().toLowerCase().replace(/_/g, " ").replace(/\s+/g, " ");
}

function buildAliasLookup(): Map<string, string> {
  const lookup = new Map<string, string>();

  for (const [field, aliases] of Object.entries(HEADER_SYNONYMS)) {
    for (const alias of aliases) lookup.set(normalizeExtractionHeader(alias), field);
  }

  return lookup;
}

const HEADER_LOOKUP = buildAliasLookup();

/**
 * Reproduces the AI parser's two supported structured modes. Extra columns
 * are tolerated just as they are by the AI service, but arbitrary headers
 * do not count toward recognized coverage.
 */
export function assessExtractionHeaders(headers: string[]): HeaderAssessment {
  const normalizedToSource = new Map<string, string>();
  for (const sourceHeader of headers) {
    const normalized = normalizeExtractionHeader(sourceHeader);
    if (!normalizedToSource.has(normalized)) normalizedToSource.set(normalized, sourceHeader);
  }

  const canonicalMapping: Record<string, string> = {};
  for (const field of CANONICAL_FIELDS) {
    const sourceHeader = normalizedToSource.get(normalizeExtractionHeader(field));
    if (sourceHeader !== undefined) canonicalMapping[sourceHeader] = field;
  }
  const hasCanonicalRequired = REQUIRED_CANONICAL_TEMPLATE_FIELDS.every((field) =>
    Object.values(canonicalMapping).includes(field)
  );

  if (hasCanonicalRequired) {
    const mappedFields = new Set(Object.values(canonicalMapping));
    return {
      mode: "TEMPLATE_COMPLIANT",
      coverageRatio: headers.length ? Object.keys(canonicalMapping).length / headers.length : 0,
      mappedFields,
      headerMapping: canonicalMapping,
      unmappedHeaders: headers.filter((header) => !(header in canonicalMapping))
    };
  }

  const mapping: Record<string, string> = {};
  for (const sourceHeader of headers) {
    const canonicalField = HEADER_LOOKUP.get(normalizeExtractionHeader(sourceHeader));
    if (canonicalField) mapping[sourceHeader] = canonicalField;
  }

  const mappedFields = new Set(Object.values(mapping));
  const coverageRatio = headers.length ? Object.keys(mapping).length / headers.length : 0;
  const hasRecognizedCore = REQUIRED_RECOGNIZED_FIELDS.every((field) => mappedFields.has(field));
  const mode: ExtractionTemplateMode =
    hasRecognizedCore && coverageRatio >= RECOGNIZED_MODE_MIN_COVERAGE
      ? "RECOGNIZED"
      : "FALLBACK";

  return {
    mode,
    coverageRatio,
    mappedFields,
    headerMapping: mode === "RECOGNIZED" ? mapping : {},
    unmappedHeaders: headers.filter((header) => !(header in mapping))
  };
}

function decodeCsv(buffer: Buffer): string | null {
  const isOleCompoundFile = buffer.subarray(0, 8).equals(
    Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1])
  );
  if (
    buffer.includes(Buffer.from("%PDF-")) ||
    (buffer[0] === 0x50 && buffer[1] === 0x4b) ||
    isOleCompoundFile
  ) {
    return null;
  }

  try {
    const encoding = buffer[0] === 0xff && buffer[1] === 0xfe
      ? "utf-16le"
      : buffer[0] === 0xfe && buffer[1] === 0xff
        ? "utf-16be"
        : "utf-8";
    const decoded = new TextDecoder(encoding, { fatal: true }).decode(buffer);
    const text = decoded.replace(/^\uFEFF/, "");
    return text.trim() ? text : null;
  } catch {
    try {
      const text = new TextDecoder("windows-1252", { fatal: true }).decode(buffer);
      return text.trim() ? text : null;
    } catch {
      return null;
    }
  }
}

function parseCsv(text: string): string[][] | null {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]!;
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"') {
      if (cell.length) return null;
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (quoted) return null;
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function assessTabularRows(rows: string[][]): boolean {
  if (rows.length < 2) return false;
  const headers = rows[0]!.map((value) => value.trim());
  const assessment = assessExtractionHeaders(headers);
  // Data Connections require the published template's required columns.
  // RECOGNIZED is useful to the AI's best-effort parser, but it does not
  // guarantee required values such as currency are mapped.
  if (assessment.mode !== "TEMPLATE_COMPLIANT") return false;

  return rows.slice(1).some((row) => row.some((value) => String(value ?? "").trim() !== ""));
}

function isExcelFile(buffer: Buffer, extension: string): boolean {
  const hasZipSignature = buffer.length >= 4 && buffer[0] === 0x50 && buffer[1] === 0x4b;
  if (!hasZipSignature) return false;

  try {
    const workbook = xlsx.read(buffer, {
      type: "buffer",
      bookVBA: extension === ".xlsm",
      sheetRows: 2
    });
    const firstSheetName = workbook.SheetNames[0];
    if (!firstSheetName) return false;
    const rows = xlsx.utils.sheet_to_json<unknown[]>(workbook.Sheets[firstSheetName]!, {
      header: 1,
      defval: "",
      raw: true,
      blankrows: false
    });
    return assessTabularRows(rows.map((row) => row.map((value) => String(value ?? ""))));
  } catch {
    return false;
  }
}

/**
 * Fast local preflight. PDFs are signature-checked here and their extracted
 * headers/rows are checked against the AI response before any database write.
 */
export function validateExtractionFileContent(extension: string, buffer: Buffer):
  | "CONTENT_EXTENSION_MISMATCH"
  | "TEMPLATE_MISMATCH"
  | null {
  if (extension === ".pdf") {
    const hasPdfSignature = buffer.subarray(0, Math.min(buffer.length, 1024)).includes(Buffer.from("%PDF-"));
    return hasPdfSignature ? null : "CONTENT_EXTENSION_MISMATCH";
  }

  if (extension === ".csv") {
    const text = decodeCsv(buffer);
    if (text === null) return "CONTENT_EXTENSION_MISMATCH";
    const rows = parseCsv(text);
    return rows && assessTabularRows(rows) ? null : "TEMPLATE_MISMATCH";
  }

  if (extension === ".xlsx" || extension === ".xlsm") {
    if (buffer[0] !== 0x50 || buffer[1] !== 0x4b) return "CONTENT_EXTENSION_MISMATCH";
    return isExcelFile(buffer, extension) ? null : "TEMPLATE_MISMATCH";
  }

  return "CONTENT_EXTENSION_MISMATCH";
}
