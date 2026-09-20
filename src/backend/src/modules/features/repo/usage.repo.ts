import { prisma } from "../../../config/database.js";

/*
 * ============================================================================
 * ACCESS-GRANTING SUBSCRIPTION STATUSES
 * ============================================================================
 *
 * These statuses mean the user is currently allowed to use
 * plan features.
 *
 * trialing:
 *   User is inside the free trial and should have access.
 *
 * active:
 *   Subscription is active normally.
 *
 * We intentionally DO NOT include:
 *
 * past_due
 * payment_failed
 * paused
 * pending
 * cancelled
 * expired
 *
 * If you later decide to provide a payment-failure grace period,
 * that should be an explicit business rule.
 */

const ACCESS_GRANTING_STATUSES = ["active", "trialing"];

/*
 * ============================================================================
 * USAGE REPOSITORY
 * ============================================================================
 */

export const usageRepository = {
  /*
   * Fetch the current usage + plan limits for the tenant's
   * access-granting subscription.
   */
  getCurrentUsageByTenant: async (tenantId: string) => {
    const now = new Date();

    return prisma.subscription.findFirst({
      where: {
        tenantId,

        status: {
          in: ACCESS_GRANTING_STATUSES
        }
      },

      include: {
        plan: {
          include: {
            planFeatures: {
              include: {
                feature: true
              }
            }
          }
        },

        subscriptionUsages: {
          where: {
            /*
             * Current usage period:
             *
             * start <= now
             * end   >  now
             *
             * Using `gt` for period_end avoids having two
             * periods match at the exact boundary.
             */
            period_start: {
              lte: now
            },

            period_end: {
              gt: now
            }
          },

          include: {
            feature: true
          }
        }
      }
    });
  },

  /*
   * Atomically increment a usage record.
   */
  increment: async (usageId: string) => {
    return prisma.subscriptionUsage.update({
      where: {
        id: usageId
      },

      data: {
        current_usage: {
          increment: 1
        }
      }
    });
  }
};

/*
 * ============================================================================
 * INCREMENT FEATURE USAGE
 * ============================================================================
 */

export const incrementUsage = async (tenantId: string, featureCode: string) => {
  const now = new Date();

  /*
   * Find the current usage record for:
   *
   * - this tenant
   * - an access-granting subscription
   * - this feature
   * - the current billing/usage period
   */
  const usageRecord = await prisma.subscriptionUsage.findFirst({
    where: {
      subscription: {
        tenantId,

        status: {
          in: ACCESS_GRANTING_STATUSES
        }
      },

      feature: {
        feature_code: featureCode
      },

      period_start: {
        lte: now
      },

      period_end: {
        gt: now
      }
    }
  });

  if (!usageRecord) {
    /*
     * Depending on how your service layer works,
     * you may prefer throwing an error here instead
     * of silently doing nothing.
     */
    return null;
  }

  /*
   * Prisma's increment operation is atomic.
   */
  return prisma.subscriptionUsage.update({
    where: {
      id: usageRecord.id
    },

    data: {
      current_usage: {
        increment: 1
      }
    }
  });
};
