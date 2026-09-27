import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";

export const ownerDb = prisma;
export const visibleCompanyScope = () => ({ deletedAt: null });

export async function companiesPage(
  where: object,
  orderBy: object,
  skip: number,
  take: number
) {
  const scope = { ...visibleCompanyScope(), ...where };
  const [items, total] = await prisma.$transaction([
    prisma.company.findMany({
      where: scope,
      orderBy,
      skip,
      take,
      include: {
        subscriptions: {
          orderBy: [{ createdAt: "desc" }, { id: "desc" }],
          take: 1,
          include: { plan: true }
        },
        _count: {
          select: {
            tenantUsers: { where: { removedAt: null } },
            products: { where: { deleted_at: null } },
            tenant_competitors: true,
            rag_documents_metadata: true
          }
        }
      }
    }),
    prisma.company.count({ where: scope })
  ]);
  return { items, total };
}

export async function companyById(id: string) {
  return prisma.company.findFirst({
    where: { ...visibleCompanyScope(), id },
    include: {
      subscriptions: {
        orderBy: [{ createdAt: "desc" }, { id: "desc" }],
        take: 1,
        include: {
          plan: { include: { planFeatures: { include: { feature: true } } } },
          subscriptionUsages: { include: { feature: true } }
        }
      },
      _count: {
        select: {
          tenantUsers: { where: { removedAt: null } },
          products: { where: { deleted_at: null } },
          tenant_competitors: true,
          rag_documents_metadata: true
        }
      }
    }
  });
}

export async function usersPage(
  platformTenantId: string,
  where: object,
  orderBy: object,
  skip: number,
  take: number
) {
  const scope = {
    tenantId: { not: platformTenantId },
    removedAt: null,
    tenant: { deletedAt: null },
    ...where
  };
  const [items, total] = await prisma.$transaction([
    prisma.tenantUser.findMany({
      where: scope,
      orderBy,
      skip,
      take,
      include: {
        user: { select: { userId: true, fullName: true, email: true } },
        tenant: { select: { id: true, businessName: true } }
      }
    }),
    prisma.tenantUser.count({ where: scope })
  ]);
  return { items, total };
}

export function userById(platformTenantId: string, id: string) {
  return prisma.tenantUser.findFirst({
    where: {
      id,
      tenantId: { not: platformTenantId },
      removedAt: null,
      tenant: { deletedAt: null }
    },
    include: {
      user: { select: { userId: true, fullName: true, email: true } },
      tenant: { select: { id: true, businessName: true } }
    }
  });
}

export async function companyIdsByCurrentSubscription(
  planId: string | undefined,
  status: string | undefined
) {
  const rows = await prisma.$queryRaw<{ tenant_id: string }[]>`
    SELECT latest.tenant_id FROM (
      SELECT DISTINCT ON (tenant_id) tenant_id, plan_id, status
      FROM subscriptions ORDER BY tenant_id, created_at DESC, id DESC
    ) AS latest
    WHERE (${planId ?? null}::uuid IS NULL OR latest.plan_id = ${planId ?? null}::uuid)
      AND (${status ?? null}::text IS NULL OR latest.status = ${status ?? null}::text)`;
  return rows.map((row) => row.tenant_id);
}

export function platformAudit(
  platformTenantId: string,
  where: object,
  skip: number,
  take: number,
  direction: "asc" | "desc" = "desc"
) {
  const scope = { tenant_id: platformTenantId, ...where };
  return prisma.$transaction([
    prisma.audit_logs.findMany({
      where: scope,
      orderBy: { created_at: direction },
      skip,
      take
    }),
    prisma.audit_logs.count({ where: scope })
  ]);
}

export function teamMemberships(platformTenantId: string) {
  return prisma.tenantUser.findMany({
    where: { tenantId: platformTenantId, removedAt: null },
    include: { user: { select: { fullName: true, email: true } } },
    orderBy: { joinedAt: "desc" }
  });
}
export function pendingInvitations(platformTenantId: string) {
  return prisma.platformInvitation.findMany({
    where: {
      tenantId: platformTenantId,
      status: "pending",
      expiresAt: { gt: new Date() }
    },
    orderBy: { createdAt: "desc" }
  });
}

export function auditWrite(
  tx: Prisma.TransactionClient,
  actor: { tenantId: string; userId: string; name: string; role: string },
  event: {
    action: string;
    domain: string;
    target: string;
    companyId?: string | null;
    changes?: { key: string; before: unknown; after: unknown }[];
  }
) {
  return tx.audit_logs.create({
    data: {
      tenant_id: actor.tenantId,
      user_id: actor.userId,
      action_type: event.action,
      target_table: event.domain,
      changed_data_json: {
        actor: actor.name,
        actorRole: actor.role,
        target: event.target,
        targetType: event.domain,
        companyId: event.companyId ?? null,
        result: "success",
        changes: (event.changes ?? []).map(({ key, before, after }) => ({
          key,
          before: before ?? null,
          after: after ?? null
        }))
      }
    }
  });
}
