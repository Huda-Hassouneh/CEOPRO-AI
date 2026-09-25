import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { PlanCreateInput } from "../../../generated/prisma/models.js";

export async function createPlan(data: PlanCreateInput) {
  return prisma.plan.create({
    data: {
      name_ar: data.name_ar,
      tierLevel: data.tierLevel,
      planType: "standard",
      tenantId: null,

      name: data.name,
      description: data.description,
      price: data.price,
      currency: data.currency,
      billingIntervalValue: data.billingIntervalValue,
      billingIntervalUnit: data.billingIntervalUnit,
      trialPeriodValue: data.trialPeriodValue ?? 0,
      paymentProviderProductId: data.paymentProviderProductId,
      paymentProviderPlanId: data.paymentProviderPlanId,
      isActive: data.isActive ?? true,

      billingOptions: data.billingOptions || [
        { period: "monthly", months: 1, discountPercent: 0 },
        { period: "three-months", months: 3, discountPercent: 10 },
        { period: "six-months", months: 6, discountPercent: 20 }
      ]
    }
  });
}

async function getPlainByName(name: string, isArabic: boolean) {
  return prisma.plan.findFirst({
    where: {
      [isArabic ? "name_ar" : "name"]: name,
      planType: "standard"
    }
  });
}

async function getPlanById(id: string) {
  return prisma.plan.findUnique({
    where: {
      id
    },
    include: {
      planFeatures: {
        include: { feature: true }
      }
    }
  });
}

async function getPlanByPriceId(id: string) {
  const legacyMatch = await prisma.plan.findUnique({
    where: { paymentProviderPlanId: id }
  });
  if (legacyMatch) return legacyMatch;

  const plans = await prisma.plan.findMany();

  return (
    plans.find((plan) => {
      const options = Array.isArray(plan.billingOptions) ? plan.billingOptions : [];
      return options.some(
        (option) =>
          typeof option === "object" &&
          option !== null &&
          "stripePriceId" in option &&
          (option as { stripePriceId?: unknown }).stripePriceId === id
      );
    }) ?? null
  );
}

async function updatePlan(id: string, data: Prisma.PlanUpdateInput) {
  return prisma.plan.update({
    where: { id },
    data
  });
}

async function getAllPlans() {
  return prisma.plan.findMany();
}


export async function getManagedStandardPlansWithLimits() {
  return prisma.plan.findMany({
    where: {
      planType: "standard",
      tenantId: null
    },
    include: {
      planFeatures: {
        include: { feature: true }
      }
    },
    orderBy: [{ tierLevel: "asc" }, { price: "asc" }]
  });
}

export async function getActivePlansWithLimits() {
  return prisma.plan.findMany({
    where: {
      isActive: true,
      planType: "standard",
      tenantId: null
    },
    include: {
      planFeatures: {
        include: {
          feature: true
        }
      }
    },
    orderBy: {
      price: "asc"
    }
  });
}

export default {
  getAllPlans,
  updatePlan,
  getPlanByPriceId,
  getPlanById,
  getPlainByName,
  createPlan,
  getActivePlansWithLimits,
  getManagedStandardPlansWithLimits
};
