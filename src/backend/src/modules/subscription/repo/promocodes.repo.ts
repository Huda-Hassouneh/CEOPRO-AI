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
  return prisma.promoCode.update({
    where: { id },
    data
  });
}
export async function insertPromocode(data: PromoCode) {
  return prisma.promoCode.create({
    data: { ...data }
  });
}
export async function consumePromocode(
  stripeSubscriptionId: string,
  stripeCouponId: string
) {
  return await prisma.$transaction(async (tx) => {
    // 2. Find the internal subscription using the Stripe ID
    const internalSubscription = await tx.subscription.findUnique({
      where: {
        paymentProviderSubscriptionId: stripeSubscriptionId
      }
    });

    if (!internalSubscription) {
      console.error(`Subscription ${stripeSubscriptionId} not found in DB.`);
      return;
    }

    // 3. Find the internal promo code using the Stripe coupon ID
    const promoCode = await tx.promoCode.findFirst({
      where: { paymentProviderCoupon: stripeCouponId }
    });

    if (promoCode) {
      // 4. Record the redemption using the internal UUIDs
      await tx.promoCodeRedemption.create({
        data: {
          promoCodeId: promoCode.id,
          subscriptionId: internalSubscription.id
        }
      });

      // 5. Increment the global usage counter
      await tx.promoCode.update({
        where: { id: promoCode.id },
        data: { usedCount: { increment: 1 } }
      });
    }
  });
}
