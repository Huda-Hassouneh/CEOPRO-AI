import { prisma } from "../../../config/database.js";
import { PromoCode } from "../../../generated/prisma/client.js";

export async function getPromoCodeByCode(code: string) {
  return prisma.promoCode.findUnique({
    where: {
      code
    }
  });
}
export async function getPromoCodeById(codeId: string) {
  return prisma.promoCode.findUnique({
    where: {
      id: codeId
    }
  });
}
export async function getPromoCodeForPlan(codeId: string, plan: string) {
  return prisma.promoCode.findFirst({
    where: {
      id: codeId,
      plans: {
        some: {
          plan: {
            id: plan
          }
        }
      }
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
