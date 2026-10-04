import { prisma } from "../../../config/database.js";
import { notificationWorkerPrisma } from "../../../config/notification-worker-database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { TenantNotificationOutboxEvent } from "../tenant-notification.types.js";

type NotificationIdentity = {
  tenantId: string;
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
  tenantId: string;
  eventType: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  titleKey: string;
  bodyKey: string;
  payload: Prisma.InputJsonValue;
  resourceType: string | null;
  resourceId: string | null;
  expiresAt: Date | null;
  dedupeKey: string;
  occurredAt: Date;
};

type RecipientArgs = {
  tenantId: string;
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
}): TenantNotificationOutboxEvent {
  return {
    id: row.id,
    tenant_id: row.tenantId,
    event_type: row.eventType,
    dedupe_key: row.dedupeKey,
    payload: normalizePayload(row.payload),
    status: row.status as TenantNotificationOutboxEvent["status"],
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

export async function getTenantNotificationRecipientUserIds(
  args: RecipientArgs
): Promise<string[]> {
  const permissionMode = args.permissionMode ?? "ANY";

  const memberships = await notificationWorkerPrisma.tenantUser.findMany({
    where: {
      tenantId: args.tenantId,
      removedAt: null,
      platformStatus: "active",
      tenant: {
        deletedAt: null,
        platformStatus: "active",
        NOT: {
          businessType: "platform"
        }
      }
    },
    select: {
      userId: true,
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

export async function claimDueEvents(
  batchSize = 20,
  leaseMs = 2 * 60 * 1000
): Promise<TenantNotificationOutboxEvent[]> {
  const safeBatchSize = Math.max(1, Math.min(Math.trunc(batchSize), 100));
  const safeLeaseMs = Math.max(30_000, Math.trunc(leaseMs));
  const now = new Date();

  const candidates =
    await notificationWorkerPrisma.tenantNotificationOutbox.findMany({
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

  const claimed: TenantNotificationOutboxEvent[] = [];

  for (const candidate of candidates) {
    const leaseUntil = new Date(Date.now() + safeLeaseMs);

    const result =
      await notificationWorkerPrisma.tenantNotificationOutbox.updateMany({
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

    const claimedRow =
      await notificationWorkerPrisma.tenantNotificationOutbox.findUnique({
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
  await tx.tenantNotification.createMany({
    data: [
      {
        tenantId: args.tenantId,
        eventType: args.eventType,
        severity: args.severity,
        titleKey: args.titleKey,
        bodyKey: args.bodyKey,
        payload: args.payload,
        resourceType: args.resourceType,
        resourceId: args.resourceId,
        expiresAt: args.expiresAt,
        dedupeKey: args.dedupeKey,
        occurredAt: args.occurredAt
      }
    ],
    skipDuplicates: true
  });

  return tx.tenantNotification.findUniqueOrThrow({
    where: {
      tenantId_dedupeKey: {
        tenantId: args.tenantId,
        dedupeKey: args.dedupeKey
      }
    }
  });
}

export async function createReceipts(
  tx: Prisma.TransactionClient,
  args: {
    notificationId: string;
    tenantId: string;
    recipientUserIds: string[];
  }
) {
  if (args.recipientUserIds.length === 0) {
    return { count: 0 };
  }

  return tx.tenantNotificationReceipt.createMany({
    data: args.recipientUserIds.map((recipientUserId) => ({
      notificationId: args.notificationId,
      tenantId: args.tenantId,
      recipientUserId
    })),
    skipDuplicates: true
  });
}

export async function markOutboxDelivered(
  tx: Prisma.TransactionClient,
  outboxId: string
): Promise<boolean> {
  const result = await tx.tenantNotificationOutbox.updateMany({
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
    await notificationWorkerPrisma.tenantNotificationOutbox.updateMany({
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
    await notificationWorkerPrisma.tenantNotificationOutbox.updateMany({
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
    await setRlsContext(tx, args.tenantId, args.recipientUserId);

    const now = new Date();

    const rows = await tx.tenantNotification.findMany({
      where: {
        tenantId: args.tenantId,
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
            tenantId: args.tenantId,
            recipientUserId: args.recipientUserId,
            ...(args.includeArchived ? {} : { archivedAt: null }),
            ...(args.unreadOnly ? { readAt: null } : {})
          }
        }
      },
      include: {
        receipts: {
          where: {
            tenantId: args.tenantId,
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
    await setRlsContext(tx, args.tenantId, args.recipientUserId);

    const now = new Date();

    return tx.tenantNotificationReceipt.count({
      where: {
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        archivedAt: null,
        notification: {
          is: {
            tenantId: args.tenantId,
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
    await setRlsContext(tx, args.tenantId, args.recipientUserId);

    const now = new Date();

    await tx.tenantNotificationReceipt.updateMany({
      where: {
        notificationId: args.notificationId,
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        notification: {
          is: {
            tenantId: args.tenantId,
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

    return tx.tenantNotificationReceipt.findFirst({
      where: {
        notificationId: args.notificationId,
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        notification: {
          is: {
            tenantId: args.tenantId,
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
    await setRlsContext(tx, args.tenantId, args.recipientUserId);

    const now = new Date();

    await tx.tenantNotificationReceipt.updateMany({
      where: {
        notificationId: args.notificationId,
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        archivedAt: null,
        notification: {
          is: {
            tenantId: args.tenantId,
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

    return tx.tenantNotificationReceipt.findFirst({
      where: {
        notificationId: args.notificationId,
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        notification: {
          is: {
            tenantId: args.tenantId,
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
    await setRlsContext(tx, args.tenantId, args.recipientUserId);

    const now = new Date();

    const result = await tx.tenantNotificationReceipt.updateMany({
      where: {
        tenantId: args.tenantId,
        recipientUserId: args.recipientUserId,
        readAt: null,
        archivedAt: null,
        notification: {
          is: {
            tenantId: args.tenantId,
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

export const tenantNotificationRepo = {
  getTenantNotificationRecipientUserIds,
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
