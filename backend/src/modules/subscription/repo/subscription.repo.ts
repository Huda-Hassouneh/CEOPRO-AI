import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";

import {
  CURRENT_SUBSCRIPTION_STATUSES,
  ACCESS_GRANTING_STATUSES
} from "../../../constants/subscription.js";

/*
 * ============================================================
 * REPOSITORY INPUT TYPES
 * ============================================================
 *
 * Prisma does NOT allow mixing:
 *
 *   tenantId: "..."
 *
 * with:
 *
 *   plan: {
 *     connect: { id: "..." }
 *   }
 *
 * inside the same checked create input.
 *
 * Webhooks/services in the application may currently provide either:
 *
 *   tenantId / planId
 *
 * OR:
 *
 *   tenant.connect / plan.connect
 *
 * This repository normalizes both forms into Prisma's
 * UncheckedCreateInput before writing to the database.
 */

type ConnectById = {
  connect?: {
    id?: string;
  };
};

type SubscriptionRepositoryCreateInput = Omit<
  Prisma.SubscriptionUncheckedCreateInput,
  "tenantId" | "planId"
> & {
  tenantId?: string;
  planId?: string;

  tenant?: ConnectById;
  plan?: ConnectById;
};

/*
 * ============================================================
 * NORMALIZE RELATION
 * ============================================================
 */

function resolveRelationId(
  directId: string | undefined,
  relation: ConnectById | undefined,
  relationName: "tenant" | "plan"
): string {
  const connectedId = relation?.connect?.id;

  /*
   * Protect against accidentally receiving two different IDs.
   */
  if (directId && connectedId && directId !== connectedId) {
    throw new Error(
      `Subscription ${relationName} relation mismatch: ` +
        `direct ID "${directId}" does not match connected ID "${connectedId}".`
    );
  }

  const resolvedId = directId ?? connectedId;

  if (!resolvedId) {
    throw new Error(
      `Subscription ${relationName} ID is required. ` +
        `Provide either ${relationName}Id or ${relationName}.connect.id.`
    );
  }

  return resolvedId;
}

/*
 * ============================================================
 * NORMALIZE CREATE DATA
 * ============================================================
 *
 * Converts mixed relation input such as:
 *
 * {
 *   tenantId: "...",
 *   plan: {
 *     connect: { id: "..." }
 *   }
 * }
 *
 * into:
 *
 * {
 *   tenantId: "...",
 *   planId: "..."
 * }
 *
 * This makes Prisma consistently use
 * SubscriptionUncheckedCreateInput.
 */

function normalizeSubscriptionCreateInput(
  data: SubscriptionRepositoryCreateInput
): Prisma.SubscriptionUncheckedCreateInput {
  const {
    tenant,
    plan,
    tenantId: directTenantId,
    planId: directPlanId,
    ...rest
  } = data;

  const tenantId = resolveRelationId(directTenantId, tenant, "tenant");

  const planId = resolveRelationId(directPlanId, plan, "plan");

  return {
    ...rest,
    tenantId,
    planId
  };
}

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
 * A current subscription means the tenant still has a
 * subscription lifecycle that should be managed.
 *
 * cancelled + expired are intentionally NOT included.
 *
 * Therefore, a tenant whose previous subscription ended can
 * create another subscription.
 */

async function getCurrentSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,

      status: {
        in: [...CURRENT_SUBSCRIPTION_STATUSES]
      }
    },
    include: {
      plan: {
        include: {
          planFeatures: { include: { feature: true } }
        }
      },
      scheduledPlan: {
        include: {
          planFeatures: { include: { feature: true } }
        }
      }
    },

    /*
     * If more than one historical/current row somehow exists,
     * return the newest relevant subscription.
     */
    orderBy: {
      createdAt: "desc"
    }
  });
}

/*
 * ============================================================
 * GET SUBSCRIPTION BY TENANT
 * ============================================================
 *
 * Backwards-compatible alias.
 */

async function getSubscriptionByTenant(tenantId: string) {
  return getCurrentSubscriptionByTenant(tenantId);
}

/*
 * ============================================================
 * ACTIVE / ACCESS-GRANTING SUBSCRIPTION
 * ============================================================
 *
 * Use when determining whether the tenant currently has
 * subscription-based access.
 */

async function getActiveSubscriptionByTenant(tenantId: string) {
  return prisma.subscription.findFirst({
    where: {
      tenantId,

      status: {
        in: [...ACCESS_GRANTING_STATUSES]
      }
    },

    orderBy: {
      createdAt: "desc"
    }
  });
}

/*
 * ============================================================
 * SUBSCRIPTION BY PAYMENT PROVIDER SUBSCRIPTION ID
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
 * SUBSCRIPTION BY INTERNAL DATABASE ID
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
 * Stripe webhooks can be delivered:
 *
 * - more than once
 * - out of order
 * - after checkout processing already created the record
 *
 * Therefore Stripe subscription creation must be idempotent.
 *
 * paymentProviderSubscriptionId should have a UNIQUE constraint
 * in the Prisma schema/database.
 */

async function createSubscription(data: SubscriptionRepositoryCreateInput) {
  /*
   * IMPORTANT:
   *
   * Normalize BEFORE handing anything to Prisma.
   *
   * This prevents the original error:
   *
   * Argument `tenant` is missing.
   *
   * Prisma now receives tenantId + planId consistently instead
   * of tenantId + plan.connect.
   */
  const normalizedData = normalizeSubscriptionCreateInput(data);

  const { paymentProviderSubscriptionId, ...updateData } = normalizedData;

  /*
   * No Stripe/provider subscription ID yet.
   *
   * This is a normal database create.
   */
  if (!paymentProviderSubscriptionId) {
    return prisma.subscription.create({
      data: normalizedData
    });
  }

  /*
   * Idempotent Stripe subscription synchronization.
   *
   * If Stripe sends the event multiple times, update the
   * existing subscription instead of inserting duplicates.
   */
  return prisma.subscription.upsert({
    where: {
      paymentProviderSubscriptionId
    },

    update: updateData,

    create: normalizedData
  });
}


async function listSubscriptionsForPlatform() {
  return prisma.subscription.findMany({
    include: {
      tenant: { select: { id: true, businessName: true } },
      plan: {
        include: {
          planFeatures: { include: { feature: true } }
        }
      },
      scheduledPlan: {
        include: {
          planFeatures: { include: { feature: true } }
        }
      }
    },
    orderBy: { createdAt: "desc" }
  });
}

/*
 * ============================================================
 * EXPORT
 * ============================================================
 */

export default {
  updateSubscription,

  /*
   * Main lifecycle query.
   */
  getCurrentSubscriptionByTenant,

  /*
   * Backwards-compatible alias.
   */
  getSubscriptionByTenant,

  /*
   * Entitlement-specific query.
   */
  getActiveSubscriptionByTenant,

  getSubscriptionByPaymentProviderId,

  getSubscriptionById,

  listSubscriptionsForPlatform,

  createSubscription
};
