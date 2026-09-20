import { prisma } from "../../../config/database.js";

import { Prisma } from "../../../generated/prisma/client.js";

import { SubscriptionCreateInput } from "../../../generated/prisma/models.js";

/*
 * A "current" subscription means the tenant still has a Stripe
 * subscription lifecycle that should be managed.
 *
 * These statuses should prevent creation of another subscription.
 */
const CURRENT_SUBSCRIPTION_STATUSES = [
  "trialing",
  "active",
  "past_due",
  "pending",
  "payment_failed",
  "paused"
];

/*
 * ============================================================
 * UPDATE SUBSCRIPTION
 * ============================================================
 */

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

/*
 * ============================================================
 * CURRENT SUBSCRIPTION BY TENANT
 * ============================================================
 *
 * This is the main query that your subscription service
 * should use.
 *
 * IMPORTANT:
 *
 * cancelled + expired are intentionally NOT included.
 *
 * Therefore a tenant whose previous subscription ended can
 * create a new subscription.
 */

async function getCurrentSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,

      status: {
        in: CURRENT_SUBSCRIPTION_STATUSES
      }
    }
  });
}

/*
 * ============================================================
 * GET SUBSCRIPTION BY TENANT
 * ============================================================
 *
 * Kept for backwards compatibility.
 *
 * Existing code calling getSubscriptionByTenant() will now
 * receive the current/ongoing subscription rather than an old
 * cancelled/expired subscription.
 */

async function getSubscriptionByTenant(tenantId: string) {
  return getCurrentSubscriptionByTenant(tenantId);
}

/*
 * ============================================================
 * ACTIVE / ACCESS-GRANTING SUBSCRIPTION
 * ============================================================
 *
 * Use this ONLY when you specifically mean:
 *
 * "Should this user currently have normal subscription access?"
 *
 * Do NOT use this to determine whether another Stripe
 * subscription can be created.
 */

async function getActiveSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,

      status: {
        in: ["active", "trialing"]
      }
    }
  });
}

/*
 * ============================================================
 * SUBSCRIPTION BY STRIPE SUBSCRIPTION ID
 * ============================================================
 */

async function getSubscriptionByPaymentProviderId(paymentProviderId: string) {
  return prisma.subscription.findFirst({
    where: {
      paymentProviderSubscriptionId: paymentProviderId
    }
  });
}

/*
 * ============================================================
 * SUBSCRIPTION BY INTERNAL DB ID
 * ============================================================
 */

async function getSubscriptionById(id: string) {
  return prisma.subscription.findUnique({
    where: {
      id
    }
  });
}

/*
 * ============================================================
 * CREATE / UPSERT SUBSCRIPTION
 * ============================================================
 *
 * The Stripe subscription ID should be UNIQUE in the database.
 *
 * Upserting makes webhook processing much safer because Stripe
 * webhook ordering is not guaranteed.
 */

async function createSubscription(data: SubscriptionCreateInput) {
  const { paymentProviderSubscriptionId, ...rest } = data;

  /*
   * If there's no provider subscription ID, regular create.
   */
  if (!paymentProviderSubscriptionId) {
    return prisma.subscription.create({
      data
    });
  }

  /*
   * Otherwise make creation idempotent around the Stripe
   * subscription ID.
   */
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

  /*
   * Main lifecycle query
   */
  getCurrentSubscriptionByTenant,

  /*
   * Backwards-compatible alias
   */
  getSubscriptionByTenant,

  /*
   * Entitlement-specific query
   */
  getActiveSubscriptionByTenant,

  getSubscriptionByPaymentProviderId,

  getSubscriptionById,

  createSubscription
};
