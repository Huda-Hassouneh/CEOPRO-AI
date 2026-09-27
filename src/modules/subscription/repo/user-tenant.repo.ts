import { prisma } from "../../../config/database.js";

export async function getActiveTenantUser(tenantId: string, userId: string) {
  return await prisma.tenantUser.findFirst({
    where: {
      userId: userId,
      tenantId: tenantId,
      removedAt: null,
      platformStatus: "active",
      tenant: { deletedAt: null, platformStatus: "active" }
    },
    include: {
      role: true
    }
  });
}
