import { prisma } from "../../../config/database.js";

export async function getActiveTenantUser(tenantId: string, userId: string) {
  return prisma.tenantUser.findFirst({
    where: {
      userId,
      tenantId,
      removedAt: null,
      platformStatus: "active",
      tenant: {
        deletedAt: null,
        platformStatus: "active"
      }
    },
    include: {
      role: true,
      tenant: {
        select: {
          businessType: true
        }
      }
    }
  });
}
