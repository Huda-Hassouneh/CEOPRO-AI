import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { CURRENT_SUBSCRIPTION_STATUSES } from "../../../constants/subscription.js";

const quoteInclude = {
  tenant: { select: { id: true, businessName: true } },
  quoteFeatures: { include: { feature: true } },
  createdPlan: { include: { planFeatures: { include: { feature: true } } } }
} as const;

export const customPlanRepository = {
  listAllQuotes: () =>
    prisma.customPlanQuote.findMany({
      include: quoteInclude,
      orderBy: { createdAt: "desc" }
    }),

  findQuoteById: (id: string) =>
    prisma.customPlanQuote.findUnique({
      where: { id },
      include: quoteInclude
    }),

  listPlatformTenants: () =>
    prisma.company.findMany({
      where: { deletedAt: null },
      select: { id: true, businessName: true, countryCode: true, primaryCurrency: true },
      orderBy: { businessName: "asc" }
    }),

  listQuotesForTenant: (tenantId: string) =>
    prisma.customPlanQuote.findMany({
      where: { tenantId },
      include: quoteInclude,
      orderBy: { createdAt: "desc" }
    }),

  findQuoteForTenant: (id: string, tenantId: string) =>
    prisma.customPlanQuote.findFirst({
      where: { id, tenantId },
      include: quoteInclude
    }),

  createQuote: async (args: {
    tenantId: string;
    createdBy?: string;
    data: Omit<Prisma.CustomPlanQuoteUncheckedCreateInput, "tenantId">;
    features: Array<{
      featureId: string;
      limitValue?: number | null;
      estimatedUsage: number;
      metadata?: Record<string, unknown>;
    }>;
  }) =>
    prisma.$transaction(async (tx) => {
      const quote = await tx.customPlanQuote.create({
        data: {
          ...args.data,
          tenantId: args.tenantId,
          createdBy: args.createdBy ?? null
        }
      });

      await tx.customPlanQuoteFeature.createMany({
        data: args.features.map((feature) => ({
          quoteId: quote.id,
          featureId: feature.featureId,
          limitValue: feature.limitValue ?? null,
          estimatedUsage: new Prisma.Decimal(feature.estimatedUsage),
          metadata: feature.metadata as Prisma.InputJsonValue | undefined
        }))
      });

      return tx.customPlanQuote.findUniqueOrThrow({
        where: { id: quote.id },
        include: quoteInclude
      });
    }),

  updateDraftQuote: async (args: {
    id: string;
    tenantId: string;
    data: Record<string, any>;
    features?: Array<{
      featureId: string;
      limitValue?: number | null;
      estimatedUsage: number;
      metadata?: Record<string, unknown>;
    }>;
  }) =>
    prisma.$transaction(async (tx) => {
      const existing = await tx.customPlanQuote.findFirst({
        where: { id: args.id, tenantId: args.tenantId }
      });
      if (!existing) return null;

      await tx.customPlanQuote.update({ where: { id: args.id }, data: args.data });

      if (args.features) {
        await tx.customPlanQuoteFeature.deleteMany({ where: { quoteId: args.id } });
        await tx.customPlanQuoteFeature.createMany({
          data: args.features.map((feature) => ({
            quoteId: args.id,
            featureId: feature.featureId,
            limitValue: feature.limitValue ?? null,
            estimatedUsage: new Prisma.Decimal(feature.estimatedUsage),
            metadata: feature.metadata as Prisma.InputJsonValue | undefined
          }))
        });
      }

      return tx.customPlanQuote.findUniqueOrThrow({
        where: { id: args.id },
        include: quoteInclude
      });
    }),

  updateQuote: (id: string, data: Record<string, any>) =>
    prisma.customPlanQuote.update({
      where: { id },
      data,
      include: quoteInclude
    }),

  getFeaturesByIds: (featureIds: string[]) =>
    prisma.feature.findMany({ where: { id: { in: featureIds } } }),

  listConfigurableFeatures: () =>
    prisma.feature.findMany({
      orderBy: [{ type: "asc" }, { name: "asc" }]
    }),

  getVendorBackedFeatureIds: async (featureIds: string[]) => {
    if (!featureIds.length) return [];
    const rows = await prisma.vendorRate.findMany({
      where: {
        featureId: { in: featureIds },
        verificationStatus: { not: "deprecated" }
      },
      select: { featureId: true },
      distinct: ["featureId"]
    });
    return rows
      .map((row) => row.featureId)
      .filter((featureId): featureId is string => Boolean(featureId));
  },

  listVendorRates: () =>
    prisma.vendorRate.findMany({
      include: { feature: true },
      orderBy: [{ vendor: "asc" }, { service: "asc" }, { effectiveFrom: "desc" }]
    }),

  getActiveVendorRates: (featureIds: string[], at = new Date()) =>
    prisma.vendorRate.findMany({
      where: {
        featureId: { in: featureIds },
        effectiveFrom: { lte: at },
        OR: [{ effectiveTo: null }, { effectiveTo: { gt: at } }],
        verificationStatus: { not: "deprecated" }
      },
      include: { feature: true }
    }),

  createVendorRate: (data: Prisma.VendorRateUncheckedCreateInput) =>
    prisma.vendorRate.create({ data, include: { feature: true } }),

  updateVendorRate: (id: string, data: Record<string, any>) =>
    prisma.vendorRate.update({ where: { id }, data, include: { feature: true } }),

  listCustomPlansForTenant: (tenantId: string) =>
    prisma.plan.findMany({
      where: { planType: "custom", tenantId, isActive: true },
      include: {
        planFeatures: { include: { feature: true } },
        activeSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: { id: true, status: true, billingPeriod: true, currentPeriodEnd: true },
          orderBy: { createdAt: "desc" },
          take: 1
        },
        scheduledSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: {
            id: true,
            status: true,
            billingPeriod: true,
            scheduledBillingPeriod: true,
            currentPeriodEnd: true,
            plan: { select: { id: true, name: true, name_ar: true } }
          },
          orderBy: { createdAt: "desc" },
          take: 1
        }
      },
      orderBy: { createdAt: "desc" }
    }),

  listAllCustomPlans: () =>
    prisma.plan.findMany({
      where: { planType: "custom" },
      include: {
        tenant: { select: { id: true, businessName: true } },
        sourceQuote: { select: { id: true, status: true, createdAt: true } },
        planFeatures: { include: { feature: true } },
        activeSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: {
            id: true,
            status: true,
            billingPeriod: true,
            currentPeriodEnd: true
          },
          orderBy: { createdAt: "desc" },
          take: 1
        },
        scheduledSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: {
            id: true,
            status: true,
            billingPeriod: true,
            scheduledBillingPeriod: true,
            currentPeriodEnd: true,
            plan: { select: { id: true, name: true, name_ar: true } }
          },
          orderBy: { createdAt: "desc" },
          take: 1
        }
      },
      orderBy: { createdAt: "desc" }
    }),

  setCustomPlanActiveState: async (id: string, isActive: boolean) => {
    const existing = await prisma.plan.findUnique({ where: { id } });
    if (!existing || existing.planType !== "custom") return null;
    return prisma.plan.update({
      where: { id },
      data: { isActive },
      include: {
        tenant: { select: { id: true, businessName: true } },
        sourceQuote: { select: { id: true, status: true, createdAt: true } },
        planFeatures: { include: { feature: true } },
        activeSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: { id: true, status: true, billingPeriod: true, currentPeriodEnd: true },
          orderBy: { createdAt: "desc" },
          take: 1
        },
        scheduledSubscriptions: {
          where: { status: { in: [...CURRENT_SUBSCRIPTION_STATUSES] } },
          select: {
            id: true,
            status: true,
            billingPeriod: true,
            scheduledBillingPeriod: true,
            currentPeriodEnd: true,
            plan: { select: { id: true, name: true, name_ar: true } }
          },
          orderBy: { createdAt: "desc" },
          take: 1
        }
      }
    });
  },

  convertQuoteToPlan: async (args: {
    quoteId: string;
    tenantId: string;
    paymentProviderProductId: string;
    billingOptions: Prisma.InputJsonValue;
    paymentProviderPlanId: string;
  }) =>
    prisma.$transaction(async (tx) => {
      const claimed = await tx.customPlanQuote.updateMany({
        where: {
          id: args.quoteId,
          tenantId: args.tenantId,
          createdPlanId: null,
          status: { in: ["approved", "sent"] }
        },
        data: { status: "accepted", acceptedAt: new Date() }
      });

      if (claimed.count !== 1) {
        return null;
      }

      const quote = await tx.customPlanQuote.findUniqueOrThrow({
        where: { id: args.quoteId },
        include: { quoteFeatures: true }
      });

      if (quote.finalPrice == null) {
        throw new Error("Approved quote has no final price");
      }

      const plan = await tx.plan.create({
        data: {
          name: quote.name,
          name_ar: quote.nameAr,
          tierLevel: null,
          planType: "custom",
          tenantId: quote.tenantId,
          description: quote.description,
          description_ar: quote.descriptionAr,
          price: quote.finalPrice,
          currency: quote.currency,
          billingIntervalValue: quote.billingIntervalValue,
          billingIntervalUnit: quote.billingIntervalUnit,
          trialPeriodValue: quote.trialPeriodValue,
          paymentProviderProductId: args.paymentProviderProductId,
          paymentProviderPlanId: args.paymentProviderPlanId,
          billingOptions: args.billingOptions,
          isActive: true
        }
      });

      if (quote.quoteFeatures.length) {
        await tx.planFeature.createMany({
          data: quote.quoteFeatures.map((feature) => ({
            plan_id: plan.id,
            feature_id: feature.featureId,
            limit_value: feature.limitValue
          }))
        });
      }

      await tx.customPlanQuote.update({
        where: { id: quote.id },
        data: { createdPlanId: plan.id }
      });

      return tx.plan.findUniqueOrThrow({
        where: { id: plan.id },
        include: { planFeatures: { include: { feature: true } } }
      });
    })
};

export default customPlanRepository;
