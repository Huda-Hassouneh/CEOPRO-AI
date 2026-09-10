import { prisma } from "../../config/database.js";
import { Plan, Prisma, PromoCode } from "../../generated/prisma/client.js";

export async function getPromoCodeByCode(code: string) {
  return prisma.promoCode.findUnique({
    where: {
      code
    }
  });
}
export async function getPromoCodeForPlan(code: string, plan: string) {
  return prisma.promoCode.findFirst({
    where: {
      code,
      plans: {
        some: {
          plan: {
            name: plan
          }
        }
      }
    }
  });
}
export async function getAllPlans() {
  return prisma.plan.findMany();
}
export async function createPlan(data: Plan) {
  return prisma.plan.create({ data: { ...data } });
}
export async function getPlainByName(name: string) {
  return prisma.plan.findUnique({
    where: {
      name
    }
  });
}

export async function getPlanById(id: string) {
  return prisma.plan.findUnique({
    where: {
      id
    }
  });
}
export async function getPromocodeById(id: string) {
  return prisma.promoCode.findUnique({
    where: {
      id
    }
  });
}
export async function getAllPromocodes() {
  return prisma.promoCode.findMany();
}
export async function updatePlan(id: string, data: Prisma.PlanUpdateInput) {
  // const { id: planId, ...d } = data;
  return prisma.plan.update({
    where: { id },
    data
  });
}
export async function updatePromocode(id: string, data: PromoCode) {
  // const { id: planId, ...d } = data;
  return prisma.promoCode.update({
    where: { id },
    data
  });
}
export async function insertPromocode(data: PromoCode) {
  // const { id: planId, ...d } = data;
  return prisma.promoCode.create({
    data: { ...data }
  });
}
export async function getPlanPromoCode(planId: string, promoCodeId: string) {
  return prisma.promoCodePlan.findUnique({
    where: {
      promoCodeId_planId: { planId, promoCodeId }
    }
  });
}
export async function linkPlanPromoCode(planId: string, promoCodeId: string) {
  return prisma.promoCodePlan.create({
    data: {
      planId,
      promoCodeId
    }
  });
}
