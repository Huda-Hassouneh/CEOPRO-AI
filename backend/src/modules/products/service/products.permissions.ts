import type { Prisma } from "../../../generated/prisma/client.js";
import type { ProductScope } from "../types/products.types.js";
import { ProductError } from "../types/products.types.js";
export async function productWriteAllowed(tx: Prisma.TransactionClient, scope: ProductScope) {
  const member = await tx.tenantUser.findFirst({ where: { tenantId: scope.tenantId, userId: scope.userId, removedAt: null, platformStatus: "active" }, include: { role: true } });
  const value = member?.role?.permissions;
  return !!value && typeof value === "object" && !Array.isArray(value) && (value.all === true || value["products.write"] === true);
}
export async function requireProductWrite(tx: Prisma.TransactionClient, scope: ProductScope) {
  if (!(await productWriteAllowed(tx, scope))) throw new ProductError("FORBIDDEN");
}
