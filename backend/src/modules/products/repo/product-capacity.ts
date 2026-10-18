import type { Prisma } from "../../../generated/prisma/client.js";
import { ProductError } from "../types/products.types.js";

export async function lockProductCatalog(tx: Prisma.TransactionClient, tenantId: string) {
  await tx.$executeRawUnsafe("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", `products-capacity:${tenantId}`);
}
export async function productCapacity(tx: Prisma.TransactionClient, tenantId: string) {
  const rows = await tx.$queryRaw<Array<{ current_usage: bigint; limit_value: number | null; is_unlimited: boolean; included: boolean }>>`
    SELECT * FROM public.product_capacity_for_tenant(${tenantId}::uuid)
  `;
  const row = rows[0];
  if (!row) throw new Error("Product capacity query returned no result.");
  return { currentUsage: Number(row.current_usage), limit: row.limit_value, isUnlimited: row.is_unlimited, included: row.included,
    remaining: row.is_unlimited ? null : Math.max(0, (row.limit_value ?? 0) - Number(row.current_usage)) };
}
export async function requireProductCapacity(tx: Prisma.TransactionClient, tenantId: string) {
  const capacity = await productCapacity(tx, tenantId);
  if (!capacity.included || (capacity.remaining !== null && capacity.remaining < 1))
    throw new ProductError("PRODUCT_CAPACITY_EXCEEDED", { feature: "tracked_products", ...capacity });
  return capacity;
}
