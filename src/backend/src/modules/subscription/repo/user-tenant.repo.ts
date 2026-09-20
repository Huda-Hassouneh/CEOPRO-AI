import { prisma } from "../../../config/database.js";

export async function getActiveTenantUser(tenantId: string, userId: string) {
  return await prisma.tenantUser.findFirst({
    where: {
      userId: userId,
      tenantId: tenantId,
      removedAt: null // Ensures they are currently active in this tenant
    },
    include: {
      role: true
    }
  });
}
