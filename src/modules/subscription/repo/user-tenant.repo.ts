import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { GetPlatformNotificationRecipientsArgs } from "../types/user-tenant.dto.js";

export async function getActiveTenantUser(tenantId: string, userId: string) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${tenantId}, true),
        set_config('app.current_user_id', ${userId}, true)
    `;

    return tx.tenantUser.findFirst({
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
  });
}

function getPermissionMap(
  permissions: Prisma.JsonValue | null
): Record<string, unknown> {
  if (
    !permissions ||
    typeof permissions !== "object" ||
    Array.isArray(permissions)
  ) {
    return {};
  }

  return permissions as Record<string, unknown>;
}

/**
 * Returns platform user IDs that are allowed to receive a
 * Platform Administration notification.
 *
 * Security rules:
 *
 * 1. Membership must belong to the canonical platform tenant.
 * 2. Membership must be active.
 * 3. Role must be owner/admin.
 * 4. Owner uses existing { all: true } authorization.
 * 5. Admin requires notifications.read.
 * 6. Admin also requires the event-domain permission.
 * 7. Empty domain permissions fail closed for admins.
 *
 * IMPORTANT:
 * source/customer tenant users are NEVER considered here.
 */
async function getPlatformNotificationRecipientUserIds(
  args: GetPlatformNotificationRecipientsArgs
): Promise<string[]> {
  const {
    platformTenantId,
    requiredPermissions,
    permissionMode = "ANY"
  } = args;

  const memberships = await prisma.tenantUser.findMany({
    where: {
      tenantId: platformTenantId,

      /*
       * Keep this aligned with the active-membership rule already
       * used by getActiveTenantUser().
       */
      removedAt: null,

      /*
       * Platform Administration role boundary.
       */
      roleKey: {
        in: ["owner", "admin"]
      },

      /*
       * Critical:
       * Having roleKey=owner/admin in a customer tenant must NOT
       * make somebody a Platform Admin.
       */
      tenant: {
        businessType: "platform",
        deletedAt: null
      }
    },

    select: {
      userId: true,
      roleKey: true,

      role: {
        select: {
          permissions: true
        }
      }
    }
  });

  const recipients = new Set<string>();

  for (const membership of memberships) {
    const permissions = getPermissionMap(membership.role?.permissions ?? null);

    /*
     * Existing owner/full-access rule.
     *
     * Your owner role currently uses:
     *
     * { all: true }
     *
     * Therefore owner automatically passes every notification
     * permission without special-casing individual domains.
     */
    if (permissions.all === true) {
      recipients.add(membership.userId);
      continue;
    }

    /*
     * Fail closed.
     *
     * A non-owner/non-full-access role must never become eligible
     * merely because it was returned by the query.
     */
    if (membership.roleKey !== "admin") {
      continue;
    }

    /*
     * First authorization layer:
     * Can this admin access the notification inbox at all?
     */
    if (permissions["notifications.read"] !== true) {
      continue;
    }

    /*
     * Empty domain permission list means the event has not been
     * configured correctly.
     *
     * Owner/full-access users were already included above.
     * Ordinary admins must NOT receive unmapped events.
     */
    if (requiredPermissions.length === 0) {
      continue;
    }

    /*
     * Second authorization layer:
     * Is this admin allowed to know about the underlying domain?
     */
    const hasDomainPermission =
      permissionMode === "ALL"
        ? requiredPermissions.every(
            (permission) => permissions[permission] === true
          )
        : requiredPermissions.some(
            (permission) => permissions[permission] === true
          );

    if (!hasDomainPermission) {
      continue;
    }

    recipients.add(membership.userId);
  }

  return [...recipients];
}
export default {
  // existing functions...
  getActiveTenantUser,

  getPlatformNotificationRecipientUserIds
};
