import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";

type PromoCreateData = {
  code: string;
  discountType: string;
  discountValue: number;
  maxUses: number;
  paymentProviderCoupon: string;
  maxUsesPerUser: number;
  startsAt: Date;
  expiresAt: Date;
  isActive: boolean;
};

type PromoUpdateData = Partial<PromoCreateData>;

export function getPromoCodeByCode(code: string) {
  return prisma.promoCode.findUnique({ where: { code } });
}

export function getPromoCodeById(codeId: string) {
  return prisma.promoCode.findUnique({ where: { id: codeId } });
}

export function getPromoCodeForPlan(codeId: string, planId: string) {
  return prisma.promoCode.findFirst({
    where: { id: codeId, plans: { some: { plan: { id: planId } } } }
  });
}

export const getPromocodeById = getPromoCodeById;

export function countPromoRedemptionsForTenant(promoCodeId: string, tenantId: string) {
  return prisma.promoCodeRedemption.count({
    where: { promoCodeId, subscription: { tenantId } }
  });
}

export function getAllPromocodes() {
  return prisma.promoCode.findMany();
}

export function updatePromocode(id: string, data: PromoUpdateData) {
  return prisma.promoCode.update({ where: { id }, data });
}

export function insertPromocode(data: PromoCreateData) {
  return prisma.promoCode.create({ data });
}

export async function consumePromocode(
  stripeSubscriptionId: string,
  stripeCouponId: string
) {
  return prisma.$transaction(async (tx) => {
    const subscription = await tx.subscription.findUnique({
      where: { paymentProviderSubscriptionId: stripeSubscriptionId }
    });
    if (!subscription) return null;

    const promoCode = await tx.promoCode.findFirst({
      where: { paymentProviderCoupon: stripeCouponId }
    });
    if (!promoCode) return null;

    const existing = await tx.promoCodeRedemption.findUnique({
      where: {
        promoCodeId_subscriptionId: {
          promoCodeId: promoCode.id,
          subscriptionId: subscription.id
        }
      }
    });
    if (existing) return existing;

    const tenantRedemptions = await tx.promoCodeRedemption.count({
      where: { promoCodeId: promoCode.id, subscription: { tenantId: subscription.tenantId } }
    });
    if (promoCode.usedCount >= promoCode.maxUses || tenantRedemptions >= promoCode.maxUsesPerUser) {
      return null;
    }

    const redemption = await tx.promoCodeRedemption.create({
      data: { promoCodeId: promoCode.id, subscriptionId: subscription.id }
    });
    await tx.promoCode.update({
      where: { id: promoCode.id },
      data: { usedCount: { increment: 1 } }
    });
    return redemption;
  }, {
    isolationLevel: Prisma.TransactionIsolationLevel.Serializable
  });
}
