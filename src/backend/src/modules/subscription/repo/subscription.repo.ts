import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { SubscriptionCreateInput } from "../../../generated/prisma/models.js";

async function updateSubscription(
  id: string,
  data: Prisma.SubscriptionUncheckedUpdateInput
) {
  return prisma.subscription.update({
    where: {
      id
    },
    data
  });
}

async function getSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,
      status: {
        in: ["pending", "active", "past_due", "payment_failed"]
      }
    }
  });
}

async function getSubscriptionByPaymentProviderId(paymentProviderId: string) {
  return prisma.subscription.findFirst({
    where: {
      paymentProviderSubscriptionId: paymentProviderId
    }
  });
}

async function getSubscriptionById(id: string) {
  return prisma.subscription.findUnique({
    where: {
      id // 👈 FIXED: Search by the internal DB ID, not the Stripe ID
    }
  });
}

async function getActiveSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,
      status: {
        in: ["active"]
      }
    }
  });
}

async function createSubscription(data: SubscriptionCreateInput) {
  const { paymentProviderSubscriptionId, ...rest } = data;

  if (!paymentProviderSubscriptionId) {
    return prisma.subscription.create({ data });
  }

  return prisma.subscription.upsert({
    where: {
      paymentProviderSubscriptionId
    },
    update: {
      ...rest
    },
    create: data
  });
}

export default {
  updateSubscription,
  getSubscriptionByTenant,
  getSubscriptionByPaymentProviderId,
  getSubscriptionById,
  getActiveSubscriptionByTenant,
  createSubscription
};
