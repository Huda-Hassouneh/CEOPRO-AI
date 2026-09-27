import {
  ownerDb,
  companiesPage,
  companyById,
  usersPage,
  userById,
  platformAudit,
  teamMemberships,
  pendingInvitations,
  visibleCompanyScope,
  companyIdsByCurrentSubscription
} from "../repo/owner.repo.js";

export type ListQuery = {
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
  direction?: "asc" | "desc";
  planId?: string;
  status?: string;
  subscriptionStatus?: string;
  country?: string;
  role?: string;
  companyId?: string;
  actor?: string;
  action?: string;
  targetType?: string;
  from?: string;
  to?: string;
};

const paging = (query: ListQuery) => {
  const page = Math.max(1, query.page || 1);
  const pageSize = Math.min(50, Math.max(1, query.pageSize || 8));
  return { page, pageSize, skip: (page - 1) * pageSize };
};
const pageResult = <T>(items: T[], total: number, query: ListQuery) => ({
  items,
  total,
  page: paging(query).page,
  pageSize: paging(query).pageSize
});
const countFields = (count: {
  tenantUsers: number;
  products: number;
  tenant_competitors: number;
  rag_documents_metadata: number;
}) => ({
  users: count.tenantUsers,
  products: count.products,
  competitors: count.tenant_competitors,
  documents: count.rag_documents_metadata
});

function subscriptionRow(row: {
  id: string;
  tenantId: string;
  status: string;
  billingPeriod: string | null;
  createdAt: Date;
  currentPeriodEnd: Date;
  plan: { id: string; name: string };
}) {
  return {
    id: row.id,
    companyId: row.tenantId,
    status: row.status,
    planId: row.plan.id,
    planName: row.plan.name,
    billingPeriod: row.billingPeriod,
    createdAt: row.createdAt,
    renewsAt: row.currentPeriodEnd,
    trialEndsAt: ["trial", "trialing"].includes(row.status)
      ? row.currentPeriodEnd
      : null
  };
}
function companyRow(
  row: Awaited<ReturnType<typeof companiesPage>>["items"][number]
) {
  const subscription = row.subscriptions[0];
  return {
    id: row.id,
    name: row.businessName,
    industry: row.businessType,
    country: row.countryCode,
    status: row.platformStatus,
    isPlatformCompany: row.businessType === "platform",
    planId: subscription?.plan.id ?? null,
    planName: subscription?.plan.name ?? null,
    subscriptionStatus: subscription?.status ?? null,
    ...countFields(row._count),
    createdAt: row.createdAt,
    updatedAt: row.updatedAt
  };
}
function userRow(row: Awaited<ReturnType<typeof usersPage>>["items"][number]) {
  return {
    id: row.id,
    userId: row.userId,
    name: row.user.fullName || row.user.email,
    email: row.user.email,
    companyId: row.tenantId,
    company: row.tenant.businessName,
    role: row.roleKey,
    status: row.platformStatus,
    createdAt: row.joinedAt
  };
}
type AuditRecord = Awaited<ReturnType<typeof platformAudit>>[0][number];
function auditRow(row: AuditRecord) {
  const meta =
    row.changed_data_json &&
    typeof row.changed_data_json === "object" &&
    !Array.isArray(row.changed_data_json)
      ? (row.changed_data_json as Record<string, unknown>)
      : {};
  return {
    id: row.audit_id,
    createdAt: row.created_at,
    actor:
      typeof meta.actor === "string" ? meta.actor : row.user_id || "System",
    actorRole: typeof meta.actorRole === "string" ? meta.actorRole : "system",
    action: row.action_type,
    targetType:
      typeof meta.targetType === "string" ? meta.targetType : row.target_table,
    target: typeof meta.target === "string" ? meta.target : row.record_id || "",
    companyId: typeof meta.companyId === "string" ? meta.companyId : null,
    result: "success",
    changes: Array.isArray(meta.changes) ? meta.changes : []
  };
}

export async function overview(platformTenantId: string) {
  const today = new Date();
  const first = new Date(
    Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 5, 1)
  );
  const months = Array.from({ length: 6 }, (_, index) => {
    const start = new Date(
      Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + index, 1)
    );
    const end = new Date(
      Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)
    );
    return { start, end, month: start.toISOString().slice(0, 7) };
  });
  const companyWhere = visibleCompanyScope();
  const [
    companies,
    users,
    active,
    trials,
    distribution,
    recent,
    audit,
    growth
  ] = await Promise.all([
    ownerDb.company.count({ where: companyWhere }),
    ownerDb.tenantUser.count({
      where: {
        tenantId: { not: platformTenantId },
        removedAt: null,
        tenant: { deletedAt: null }
      }
    }),
    ownerDb.subscription.count({
      where: { tenant: companyWhere, status: "active" }
    }),
    ownerDb.subscription.count({
      where: { tenant: companyWhere, status: { in: ["trial", "trialing"] } }
    }),
    ownerDb.subscription.groupBy({
      by: ["planId"],
      where: {
        tenant: companyWhere,
        status: { in: ["active", "trial", "trialing"] }
      },
      _count: { _all: true }
    }),
    companiesPage({}, { createdAt: "desc" }, 0, 4),
    platformAudit(platformTenantId, {}, 0, 5),
    Promise.all(
      months.map(async ({ start, end, month }) => ({
        month,
        companies: await ownerDb.company.count({
          where: { ...companyWhere, createdAt: { gte: start, lt: end } }
        }),
        users: await ownerDb.tenantUser.count({
          where: {
            tenantId: { not: platformTenantId },
            removedAt: null,
            tenant: { deletedAt: null },
            joinedAt: { gte: start, lt: end }
          }
        })
      }))
    )
  ]);
  const plans = await ownerDb.plan.findMany({
    where: { id: { in: distribution.map((d) => d.planId) } },
    select: { id: true, name: true }
  });
  return {
    companies,
    users,
    active,
    trials,
    growth,
    distribution: distribution.map((d) => ({
      planId: d.planId,
      planName: plans.find((p) => p.id === d.planId)?.name ?? d.planId,
      count: d._count._all
    })),
    recentCompanies: recent.items.map(companyRow),
    activity: audit[0].map(auditRow)
  };
}

export async function companies(_platformTenantId: string, query: ListQuery) {
  const { skip, pageSize } = paging(query);
  const matchingSubscriptions =
    query.planId || query.subscriptionStatus
      ? await companyIdsByCurrentSubscription(
          query.planId,
          query.subscriptionStatus
        )
      : null;
  const where = {
    ...(query.q && {
      businessName: { contains: query.q, mode: "insensitive" }
    }),
    ...(query.country && { countryCode: query.country }),
    ...(query.status && { platformStatus: query.status }),
    ...(matchingSubscriptions && { id: { in: matchingSubscriptions } })
  };
  const sort =
    (
      {
        name: "businessName",
        country: "countryCode",
        industry: "businessType",
        status: "platformStatus"
      } as Record<string, string>
    )[query.sort || ""] || "createdAt";
  const result = await companiesPage(
    where,
    { [sort]: query.direction || "desc" },
    skip,
    pageSize
  );
  const [plans, countries] = await Promise.all([
    ownerDb.plan.findMany({
      where: { isActive: true },
      select: { id: true, name: true },
      orderBy: { name: "asc" }
    }),
    ownerDb.company.findMany({
      where: visibleCompanyScope(),
      select: { countryCode: true },
      distinct: ["countryCode"]
    })
  ]);
  return {
    ...pageResult(result.items.map(companyRow), result.total, query),
    facets: {
      plans: plans.map((p) => ({ value: p.id, label: p.name })),
      countries: countries.map((c) => c.countryCode).sort()
    }
  };
}
export async function companyDetail(platformTenantId: string, id: string) {
  const row = await companyById(id);
  if (!row) return null;
  const recentAudit = await platformAudit(
    platformTenantId,
    {
      changed_data_json: { path: ["companyId"], equals: id }
    },
    0,
    20
  );
  const base = companyRow(row);
  const subscription = row.subscriptions[0];
  const limits: Record<string, number | null> = {};
  const usage: Record<string, number> = {};
  for (const entry of subscription?.plan.planFeatures ?? []) {
    const key = {
      tracked_competitors: "competitors",
      rag_queries: "ragQueries",
      report_generation: "reports",
      storage_gb: "storageGb",
      products: "products"
    }[
      entry.feature.code as
        | "tracked_competitors"
        | "rag_queries"
        | "report_generation"
        | "storage_gb"
        | "products"
    ];
    if (key) limits[key] = entry.limit_value;
  }
  for (const entry of subscription?.subscriptionUsages ?? []) {
    if (entry.period_start <= new Date() && entry.period_end > new Date()) {
      const key =
        entry.feature.code === "rag_queries"
          ? "ragQueries"
          : entry.feature.code === "report_generation"
            ? "reports"
            : null;
      if (key) usage[key] = (usage[key] || 0) + entry.current_usage;
    }
  }
  usage.products = row._count.products;
  usage.competitors = row._count.tenant_competitors;
  return {
    ...base,
    notes: row.platformNotes || "",
    subscription: subscription ? subscriptionRow(subscription) : null,
    limits,
    usage,
    activity: recentAudit[0].map(auditRow)
  };
}

export async function users(platformTenantId: string, query: ListQuery) {
  const { skip, pageSize } = paging(query);
  const where = {
    ...(query.companyId && { tenantId: query.companyId }),
    ...(query.role && { roleKey: query.role }),
    ...(query.status && { platformStatus: query.status }),
    ...(query.q && {
      OR: [
        { user: { fullName: { contains: query.q, mode: "insensitive" } } },
        { user: { email: { contains: query.q, mode: "insensitive" } } },
        { tenant: { businessName: { contains: query.q, mode: "insensitive" } } }
      ]
    })
  };
  const direction = query.direction || "desc";
  const orderBy =
    query.sort === "name"
      ? { user: { fullName: direction } }
      : query.sort === "company"
        ? { tenant: { businessName: direction } }
        : query.sort === "role"
          ? { roleKey: direction }
          : query.sort === "status"
            ? { platformStatus: direction }
            : { joinedAt: direction };
  const result = await usersPage(
    platformTenantId,
    where,
    orderBy,
    skip,
    pageSize
  );
  const companyList = await ownerDb.company.findMany({
    where: { ...visibleCompanyScope(), id: { not: platformTenantId } },
    select: { id: true, businessName: true },
    orderBy: { businessName: "asc" }
  });
  return {
    ...pageResult(result.items.map(userRow), result.total, query),
    facets: {
      companies: companyList.map((c) => ({
        value: c.id,
        label: c.businessName
      }))
    }
  };
}
export async function userDetail(platformTenantId: string, id: string) {
  const row = await userById(platformTenantId, id);
  return row ? userRow(row) : null;
}

export async function auditLogs(platformTenantId: string, query: ListQuery) {
  const { skip, pageSize } = paging(query);
  const toDate = query.to ? new Date(`${query.to}T00:00:00Z`) : null;
  toDate?.setUTCDate(toDate.getUTCDate() + 1);
  const jsonFilters = [
    ...(query.companyId
      ? [
          {
            changed_data_json: { path: ["companyId"], equals: query.companyId }
          }
        ]
      : []),
    ...(query.actor
      ? [{ changed_data_json: { path: ["actor"], equals: query.actor } }]
      : [])
  ];
  const where = {
    ...(query.action && { action_type: query.action }),
    ...(query.targetType && { target_table: query.targetType }),
    ...((query.from || toDate) && {
      created_at: {
        ...(query.from && { gte: new Date(`${query.from}T00:00:00Z`) }),
        ...(toDate && { lt: toDate })
      }
    }),
    ...(jsonFilters.length && { AND: jsonFilters }),
    ...(query.q && {
      OR: [
        { action_type: { contains: query.q, mode: "insensitive" } },
        { target_table: { contains: query.q, mode: "insensitive" } },
        { changed_data_json: { path: ["actor"], string_contains: query.q } },
        { changed_data_json: { path: ["target"], string_contains: query.q } }
      ]
    })
  };
  const [items, total] = await platformAudit(
    platformTenantId,
    where,
    skip,
    pageSize,
    query.direction
  );
  const actors = await ownerDb.audit_logs.findMany({
    where: { tenant_id: platformTenantId },
    select: { changed_data_json: true },
    orderBy: { created_at: "desc" },
    take: 500
  });
  return {
    ...pageResult(items.map(auditRow), total, query),
    facets: {
      actors: [
        ...new Set(
          actors
            .map((a) => {
              const raw = a.changed_data_json;
              return raw &&
                typeof raw === "object" &&
                !Array.isArray(raw) &&
                typeof (raw as Record<string, unknown>).actor === "string"
                ? (raw as Record<string, string>).actor
                : "";
            })
            .filter(Boolean)
        )
      ].map((actor) => ({ value: actor, label: actor }))
    }
  };
}

export async function team(platformTenantId: string, query: ListQuery) {
  const [members, invitations] = await Promise.all([
    teamMemberships(platformTenantId),
    pendingInvitations(platformTenantId)
  ]);
  const rows = [
    ...members.map((m) => ({
      id: m.id,
      name: m.user.fullName || "",
      email: m.user.email,
      role: m.roleKey,
      status: m.platformStatus,
      createdAt: m.joinedAt
    })),
    ...invitations.map((i) => ({
      id: i.id,
      name: "",
      email: i.email,
      role: i.roleKey,
      status: "pending",
      createdAt: i.createdAt
    }))
  ];
  const filtered = rows.filter(
    (r) =>
      (!query.q ||
        [r.name, r.email].some((v) =>
          v.toLowerCase().includes(query.q!.toLowerCase())
        )) &&
      (!query.role || r.role === query.role) &&
      (!query.status || r.status === query.status)
  );
  const sort = ["name", "email", "role", "status"].includes(query.sort || "")
    ? (query.sort as "name" | "email" | "role" | "status")
    : "createdAt";
  filtered.sort(
    (a, b) =>
      String(a[sort] || "").localeCompare(String(b[sort] || ""), undefined, {
        numeric: true
      }) * (query.direction === "asc" ? 1 : -1)
  );
  const { skip, pageSize } = paging(query);
  return pageResult(
    filtered.slice(skip, skip + pageSize),
    filtered.length,
    query
  );
}

export async function settings(platformTenantId: string) {
  const [company, config] = await Promise.all([
    ownerDb.company.findUnique({
      where: { id: platformTenantId },
      select: {
        businessName: true,
        preferredLanguage: true,
        primaryCurrency: true
      }
    }),
    ownerDb.appConfig.findUnique({ where: { key: "platform.supportEmail" } })
  ]);
  if (!company) return null;
  return {
    name: company.businessName,
    supportEmail: config?.value || "",
    language: company.preferredLanguage,
    currency: company.primaryCurrency
  };
}
