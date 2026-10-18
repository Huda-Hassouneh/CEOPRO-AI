import {randomUUID} from "node:crypto";
import type {Prisma} from "../../../generated/prisma/client.js";
import {requireProductCapacity} from "../../products/repo/product-capacity.js";

export class ImportProductError extends Error {}
export async function ensureImportedProduct(
  tx: Prisma.TransactionClient,
  tenantId: string,
  productName: string,
  unitPrice: string,
  currency: string,
  jobId: string,
  productCache: Map<string, string>,
  sku: string | null = null
): Promise<string> {
  const normalizedName = productName.trim().toLocaleLowerCase("en-US");
  const cacheKey = `${tenantId}:${sku ? `sku:${sku.toLowerCase()}` : `name:${normalizedName}`}`;
  const cached = productCache.get(cacheKey);
  if (cached) return cached;

  // Serialize matching-product creation across concurrent imports for the
  // same tenant/name pair. The returned column is UUID (never PostgreSQL void).
  const lockKey = cacheKey;
  const matches = await tx.$queryRaw<Array<{ product_id: string | null; deleted_at: Date | null }>>`
    WITH product_name_lock AS MATERIALIZED (
      SELECT pg_advisory_xact_lock(hashtextextended(${lockKey}, 0))
    )
    SELECT existing.product_id, existing.deleted_at
    FROM product_name_lock
    LEFT JOIN LATERAL (
      SELECT p.product_id, p.deleted_at
      FROM products p
      WHERE p.tenant_id = ${tenantId}::uuid
        AND CASE WHEN ${sku}::text IS NOT NULL THEN lower(btrim(p.sku)) = lower(${sku}::text)
          ELSE lower(btrim(p.product_name ->> 'en')) = ${normalizedName}
            OR lower(btrim(p.product_name ->> 'ar')) = ${normalizedName}
            OR lower(btrim(CASE WHEN jsonb_typeof(p.product_name) = 'string' THEN p.product_name #>> '{}' ELSE p.product_name ->> 'name' END)) = ${normalizedName}
            OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(p.metadata -> 'import_name_aliases') = 'array'
              THEN p.metadata -> 'import_name_aliases' ELSE '[]'::jsonb END) AS alias(value) WHERE lower(btrim(alias.value)) = ${normalizedName}) END
      ORDER BY (p.deleted_at IS NOT NULL), p.created_at ASC NULLS FIRST, p.product_id ASC
      LIMIT 2
    ) AS existing ON TRUE
  `;

  const activeMatches = matches.filter((row) => row.product_id && !row.deleted_at);
  if (activeMatches.length > 1) throw new ImportProductError("More than one active product matches this row. Supply a unique SKU or resolve the product names.");
  const existingId = activeMatches[0]?.product_id;
  if (existingId) {
    productCache.set(cacheKey, existingId);
    return existingId;
  }

  if (matches.some((row) => row.product_id)) throw new ImportProductError("This product is archived. Restore it before importing more sales.");
  await requireProductCapacity(tx, tenantId);
  const product = await tx.products.create({
    data: {
      product_id: randomUUID(),
      tenant_id: tenantId,
      product_name: { en: productName },
      sku,
      current_price: unitPrice,
      currency,
      source: "IMPORTED",
      metadata: {
        import_job_id: jobId,
        import_source: "data_connection"
      }
    },
    select: { product_id: true }
  });

  productCache.set(cacheKey, product.product_id);
  return product.product_id;
}

