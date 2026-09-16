import { prisma } from "../../../config/database.js";

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
