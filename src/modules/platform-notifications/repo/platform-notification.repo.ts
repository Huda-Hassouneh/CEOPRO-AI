import { prisma } from "../../../config/database.js";
import { notificationWorkerPrisma } from "../../../config/notification-worker-database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { PlatformNotificationOutboxEvent } from "../platform-notification.types.js";

type NotificationIdentity = {
  platformTenantId: string;
  recipientUserId: string;
};

type ListForRecipientArgs = NotificationIdentity & {
  limit: number;
  cursor?: string;
  unreadOnly?: boolean;
  includeArchived?: boolean;
};

type NotificationActionArgs = NotificationIdentity & {
  notificationId: string;
};

type CreateNotificationArgs = {
  platformTenantId: string;
  sourceTenantId: string | null;
  eventType: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  titleKey: string;
  bodyKey: string;
  payload: Prisma.InputJsonValue;
  resourceType: string | null;
  resourceId: string | null;
  dedupeKey: string;
  occurredAt: Date;
};

type RecipientArgs = {
  platformTenantId: string;
  requiredPermissions: string[];
  permissionMode?: "ANY" | "ALL";
};

function normalizePayload(payload: Prisma.JsonValue): Record<string, unknown> {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }

  return {};
}

function permissionMap(value: Prisma.JsonValue): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  return {};
}

function toOutboxEvent(row: {
  id: string;
  tenantId: string;
  eventType: string;
  dedupeKey: string;
  payload: Prisma.JsonValue;
  status: string;
  attempts: number;
  occurredAt: Date;
  nextAttemptAt: Date;
  deliveredAt: Date | null;
  lastErrorCode: string | null;
  createdAt: Date;
}): PlatformNotificationOutboxEvent {
  return {
    id: row.id,
    tenant_id: row.tenantId,
    event_type: row.eventType,
    dedupe_key: row.dedupeKey,
    payload: normalizePayload(row.payload),
    status: row.status as PlatformNotificationOutboxEvent["status"],
    attempts: row.attempts,
    occurred_at: row.occurredAt,
    next_attempt_at: row.nextAttemptAt,
    delivered_at: row.deliveredAt,
    last_error_code: row.lastErrorCode,
    created_at: row.createdAt
  };
}

async function setRlsContext(
  tx: Prisma.TransactionClient,
  tenantId: string,
  userId: string
): Promise<void> {
  await tx.$queryRaw`
    SELECT
      set_config('app.current_tenant_id', ${tenantId}, true),
      set_config('app.current_user_id', ${userId}, true)
  `;
}

export async function getPlatformTenantId(): Promise<string> {
  const rows = await notificationWorkerPrisma.company.findMany({
    where: {
      businessType: "platform",
      deletedAt: null,
      platformStatus: "active"
    },
    select: {
      id: true
    },
    take: 2
  });

  if (rows.length === 0) {
    throw new Error("No active CEOPRO platform tenant was found");
  }

  if (rows.length > 1) {
    throw new Error("Multiple active CEOPRO platform tenants were found");
  }

  return rows[0].id;
}

export async function getPlatformNotificationRecipientUserIds(
  args: RecipientArgs
): Promise<string[]> {
  const permissionMode = args.permissionMode ?? "ANY";

  const memberships = await notificationWorkerPrisma.tenantUser.findMany({
    where: {
      tenantId: args.platformTenantId,
      removedAt: null,
      platformStatus: "active",
      roleKey: {
        in: ["owner", "admin"]
      },
      tenant: {
        businessType: "platform",
        deletedAt: null,
        platformStatus: "active"
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
    const permissions = permissionMap(membership.role.permissions);

    if (permissions.all === true) {
      recipients.add(membership.userId);
      continue;
    }

    if (membership.roleKey !== "admin") {
      continue;
    }

    if (permissions["notifications.read"] !== true) {
      continue;
    }

    if (args.requiredPermissions.length === 0) {
      continue;
    }

    const hasDomainPermission =
      permissionMode === "ALL"
        ? args.requiredPermissions.every(
            (permission) => permissions[permission] === true
          )
        : args.requiredPermissions.some(
            (permission) => permissions[permission] === true
          );

    if (hasDomainPermission) {
      recipients.add(membership.userId);
    }
  }

  return [...recipients];
}

/**
 * Claims a bounded batch using a compare-and-set lease.
 *
 * This is intentionally Prisma-only. Two workers can read the same candidate,
 * but only one can move nextAttemptAt into the future while the original lease
 * is still due. The second update then affects zero rows.
 *
 * Production note: these worker methods require a trusted, narrowly-scoped
 * database capability because the notification tables use FORCE RLS.
 */
export async function claimDueEvents(
  batchSize = 20,
  leaseMs = 2 * 60 * 1000
): Promise<PlatformNotificationOutboxEvent[]> {
  const safeBatchSize = Math.max(1, Math.min(Math.trunc(batchSize), 100));
  const safeLeaseMs = Math.max(30_000, Math.trunc(leaseMs));
  const now = new Date();

  const candidates =
    await notificationWorkerPrisma.platformNotificationOutbox.findMany({
      where: {
        status: {
          in: ["pending", "processing"]
        },
        nextAttemptAt: {
          lte: now
        }
      },
      orderBy: [{ nextAttemptAt: "asc" }, { id: "asc" }],
      take: safeBatchSize
    });

  const claimed: PlatformNotificationOutboxEvent[] = [];

  for (const candidate of candidates) {
    const leaseUntil = new Date(Date.now() + safeLeaseMs);

    const result = await prisma.platformNotificationOutbox.updateMany({
      where: {
        id: candidate.id,
        status: {
          in: ["pending", "processing"]
        },
        nextAttemptAt: {
          lte: now
        }
      },
      data: {
        status: "processing",
        attempts: {
          increment: 1
        },
        nextAttemptAt: leaseUntil
      }
    });

    if (result.count !== 1) {
      continue;
    }

    const claimedRow = await prisma.platformNotificationOutbox.findUnique({
      where: {
        id: candidate.id
      }
    });

    if (claimedRow) {
      claimed.push(toOutboxEvent(claimedRow));
    }
  }

  return claimed;
}

export async function createNotification(
  tx: Prisma.TransactionClient,
  args: CreateNotificationArgs
) {
  try {
    return await tx.platformNotification.create({
      data: {
        platformTenantId: args.platformTenantId,

        sourceTenantId: args.sourceTenantId,

        eventType: args.eventType,

        severity: args.severity,

        titleKey: args.titleKey,

        bodyKey: args.bodyKey,

        payload: args.payload,

        resourceType: args.resourceType,

        resourceId: args.resourceId,

        dedupeKey: args.dedupeKey,

        occurredAt: args.occurredAt
      }
    });
  } catch (error) {
    const code =
      error && typeof error === "object" && "code" in error
        ? (error as { code?: unknown }).code
        : undefined;

    if (code !== "P2002") {
      throw error;
    }

    const existing = await tx.platformNotification.findUnique({
      where: {
        platformTenantId_dedupeKey: {
          platformTenantId: args.platformTenantId,

          dedupeKey: args.dedupeKey
        }
      }
    });

    if (!existing) {
      throw error;
    }

    return existing;
  }
}

export async function createReceipts(
  tx: Prisma.TransactionClient,
  args: {
    notificationId: string;
    platformTenantId: string;
    recipientUserIds: string[];
  }
) {
  if (args.recipientUserIds.length === 0) {
    return { count: 0 };
  }

  return tx.platformNotificationReceipt.createMany({
    data: args.recipientUserIds.map((recipientUserId) => ({
      notificationId: args.notificationId,
      platformTenantId: args.platformTenantId,
      recipientUserId
    })),
    skipDuplicates: true
  });
}

export async function markOutboxDelivered(
  tx: Prisma.TransactionClient,
  outboxId: string
): Promise<boolean> {
  const result = await tx.platformNotificationOutbox.updateMany({
    where: {
      id: outboxId,
      status: "processing"
    },
    data: {
      status: "delivered",
      deliveredAt: new Date(),
      lastErrorCode: null
    }
  });

  return result.count === 1;
}

export async function rescheduleOutboxEvent(
  outboxId: string,
  args: {
    nextAttemptAt: Date;
    errorCode: string;
  }
): Promise<boolean> {
  const result =
    await notificationWorkerPrisma.platformNotificationOutbox.updateMany({
      where: {
        id: outboxId,
        status: "processing"
      },
      data: {
        status: "pending",
        nextAttemptAt: args.nextAttemptAt,
        lastErrorCode: args.errorCode.slice(0, 100)
      }
    });

  return result.count === 1;
}

export async function markOutboxFailed(
  outboxId: string,
  errorCode: string
): Promise<boolean> {
  const result =
    await notificationWorkerPrisma.platformNotificationOutbox.updateMany({
      where: {
        id: outboxId,
        status: "processing"
      },
      data: {
        status: "failed",
        lastErrorCode: errorCode.slice(0, 100)
      }
    });

  return result.count === 1;
}

export async function listForRecipient(args: ListForRecipientArgs) {
  return prisma.$transaction(async (tx) => {
    await setRlsContext(tx, args.platformTenantId, args.recipientUserId);

    const now = new Date();

    const rows = await tx.platformNotification.findMany({
      where: {
        platformTenantId: args.platformTenantId,
        OR: [
          { expiresAt: null },
          {
            expiresAt: {
              gt: now
            }
          }
        ],
        receipts: {
          some: {
            platformTenantId: args.platformTenantId,
            recipientUserId: args.recipientUserId,
            ...(args.includeArchived ? {} : { archivedAt: null }),
            ...(args.unreadOnly ? { readAt: null } : {})
          }
        }
      },
      include: {
        receipts: {
          where: {
            platformTenantId: args.platformTenantId,
            recipientUserId: args.recipientUserId
          },
          select: {
            readAt: true,
            archivedAt: true,
            createdAt: true
          },
          take: 1
        }
      },
      orderBy: [{ createdAt: "desc" }, { id: "desc" }],
      take: args.limit + 1,
      ...(args.cursor
        ? {
            cursor: {
              id: args.cursor
            },
            skip: 1
          }
        : {})
    });

    const hasMore = rows.length > args.limit;
    const page = hasMore ? rows.slice(0, args.limit) : rows;

    return {
      items: page.map((row) => {
        const receipt = row.receipts[0];

        return {
          id: row.id,
          eventType: row.eventType,
          severity: row.severity,
          titleKey: row.titleKey,
          bodyKey: row.bodyKey,
          payload: row.payload,
          sourceTenantId: row.sourceTenantId,
          resourceType: row.resourceType,
          resourceId: row.resourceId,
          occurredAt: row.occurredAt,
          createdAt: row.createdAt,
          expiresAt: row.expiresAt,
          readAt: receipt?.readAt ?? null,
          archivedAt: receipt?.archivedAt ?? null
        };
      }),
      nextCursor: hasMore && page.length > 0 ? page[page.length - 1].id : null
    };
  });
}

export async function countUnreadForRecipient(
  args: NotificationIdentity
): Promise<number> {
  return prisma.$transaction(async (tx) => {
    await setRlsContext(tx, args.platformTenantId, args.recipientUserId);

    const now = new Date();

    return tx.platformNotificationReceipt.count({
      where: {
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        archivedAt: null,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      }
    });
  });
}

export async function markReadForRecipient(args: NotificationActionArgs) {
  return prisma.$transaction(async (tx) => {
    await setRlsContext(tx, args.platformTenantId, args.recipientUserId);

    const now = new Date();

    await tx.platformNotificationReceipt.updateMany({
      where: {
        notificationId: args.notificationId,
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      },
      data: {
        readAt: now
      }
    });

    return tx.platformNotificationReceipt.findFirst({
      where: {
        notificationId: args.notificationId,
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      }
    });
  });
}

export async function archiveForRecipient(args: NotificationActionArgs) {
  return prisma.$transaction(async (tx) => {
    await setRlsContext(tx, args.platformTenantId, args.recipientUserId);

    const now = new Date();

    await tx.platformNotificationReceipt.updateMany({
      where: {
        notificationId: args.notificationId,
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        archivedAt: null,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      },
      data: {
        archivedAt: now
      }
    });

    return tx.platformNotificationReceipt.findFirst({
      where: {
        notificationId: args.notificationId,
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      }
    });
  });
}

export async function markAllReadForRecipient(
  args: NotificationIdentity
): Promise<number> {
  return prisma.$transaction(async (tx) => {
    await setRlsContext(tx, args.platformTenantId, args.recipientUserId);

    const now = new Date();

    const result = await tx.platformNotificationReceipt.updateMany({
      where: {
        platformTenantId: args.platformTenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        archivedAt: null,
        notification: {
          is: {
            platformTenantId: args.platformTenantId,
            OR: [
              { expiresAt: null },
              {
                expiresAt: {
                  gt: now
                }
              }
            ]
          }
        }
      },
      data: {
        readAt: now
      }
    });

    return result.count;
  });
}

export const platformNotificationRepo = {
  getPlatformTenantId,
  getPlatformNotificationRecipientUserIds,
  claimDueEvents,
  createNotification,
  createReceipts,
  markOutboxDelivered,
  rescheduleOutboxEvent,
  markOutboxFailed,
  listForRecipient,
  countUnreadForRecipient,
  markReadForRecipient,
  archiveForRecipient,
  markAllReadForRecipient
};
