import type { InvoiceItemImportRow, InventoryImportRow, ParsedBusinessImport } from "./structured-business-import.js";
import { normalizeProductReference } from "./structured-business-import.js";

export type ProductReferenceRow = InvoiceItemImportRow | InventoryImportRow;
export type CatalogProduct = {
  product_id: string;
  product_name: unknown;
  sku: string | null;
  currency: string;
  current_price?: unknown;
  brand?: unknown;
  category?: unknown;
  created_at?: Date | null;
  metadata?: unknown;
};
export type ProductMatch = {
  key: string;
  sheet: string;
  row: number;
  productName: string;
  sku: string;
  status: "matched" | "missing" | "ambiguous" | "conflict";
  productId: string | null;
  candidates: CatalogProduct[];
  message: string | null;
};

export function productRows(parsed: ParsedBusinessImport): ProductReferenceRow[] {
  return parsed.kind === "invoices" ? parsed.items : parsed.inventory;
}

export function productRowKey(row: ProductReferenceRow): string {
  return `${row.sheet}:${row.row}`;
}

function productNames(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.values(value).filter((name): name is string => typeof name === "string");
  }
  return [];
}

export function matchProduct(row: ProductReferenceRow, products: CatalogProduct[]): ProductMatch {
  const matchingNames = (product: CatalogProduct) => {
    const metadata = product.metadata && typeof product.metadata === "object" && !Array.isArray(product.metadata) ? product.metadata as Record<string, unknown> : {};
    const aliases = Array.isArray(metadata.import_name_aliases) ? metadata.import_name_aliases.filter((name): name is string => typeof name === "string") : [];
    return [...productNames(product.product_name), ...aliases];
  };
  const predicates = [
    row.productId ? (product: CatalogProduct) => product.product_id.toLowerCase() === row.productId : null,
    row.sku ? (product: CatalogProduct) => product.sku != null && normalizeProductReference(product.sku) === normalizeProductReference(row.sku) : null,
    row.productName ? (product: CatalogProduct) => matchingNames(product).some((name) => normalizeProductReference(name) === normalizeProductReference(row.productName)) : null
  ].filter((predicate): predicate is (product: CatalogProduct) => boolean => predicate !== null);
  const individual = predicates.map((predicate) => products.filter(predicate));
  const candidates = products.filter((product) => predicates.every((predicate) => predicate(product)));
  const conflict = individual.some((matches) => matches.length === 0) && individual.some((matches) => matches.length > 0) ||
    (candidates.length === 0 && individual.every((matches) => matches.length > 0));
  const status = conflict ? "conflict" : candidates.length === 1 ? "matched" : candidates.length === 0 ? "missing" : "ambiguous";
  return {
    key: productRowKey(row), sheet: row.sheet, row: row.row,
    productName: row.productName, sku: row.sku, status,
    productId: status === "matched" ? candidates[0]!.product_id : null,
    candidates: status === "ambiguous" ? candidates : [],
    message: status === "conflict" ? "Product ID, SKU, and name refer to different products. Correct this file and upload it again."
      : status === "missing" ? "No active product matches this row. Select a product or create one."
      : status === "ambiguous" ? "More than one active product has this name. Choose the right one."
      : null
  };
}

export function matchImportProducts(parsed: ParsedBusinessImport, products: CatalogProduct[]): ProductMatch[] {
  return productRows(parsed).map((row) => matchProduct(row, products));
}
