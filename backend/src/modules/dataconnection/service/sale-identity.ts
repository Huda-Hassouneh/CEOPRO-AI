import { createHash } from "node:crypto";
import type { SalesStagingRow } from "./sales-staging-row.js";

export function saleIdentity(payload: unknown, sale: SalesStagingRow) {
  const fields = payload as Record<string, unknown>;
  const saleId = fields.sale_id == null ? "" : String(fields.sale_id).trim();
  const source = fields.source_system == null ? "" : String(fields.source_system).trim();
  // Older exports may already contain a source-system column without sale IDs.
  // Preserve those anonymous sales instead of guessing an identity or rejecting them.
  if (!saleId) return null;
  if (!["string","number"].includes(typeof fields.sale_id) ||
      (fields.source_system != null && !["string","number"].includes(typeof fields.source_system)))
    throw new Error("sale_id/source_system must be scalar identifiers.");
  if (saleId.length > 200 || source.length > 100 || /[\u0000-\u001f]/.test(saleId + source))
    throw new Error("sale_id/source_system is invalid or exceeds its length limit.");
  const sourceSystem = source || "manual-import";
  const hash = createHash("sha256").update(JSON.stringify([
    "sale-v1", sale.sku?.toLowerCase() ?? sale.productName.trim().toLocaleLowerCase("en-US"), sale.quantity, sale.unitPrice, sale.totalPrice, sale.currency, sale.transactionDate.toISOString()
  ])).digest("hex");
  return { saleId, sourceSystem, hash, key: JSON.stringify([sourceSystem, saleId]) };
}
