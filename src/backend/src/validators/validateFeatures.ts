import { Response, NextFunction } from "express";
import { prisma } from "../config/database.js";
import { errorResponse } from "../types/response.js";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-defentions.js";

export const requireTenant = (
  req: any,
  res: Response,
  next: NextFunction
): void => {
  // Option A: Extract from the decoded JWT payload (Recommended for SaaS)
  const userPayload = req.user as any;

  const tenantId = userPayload?.tenant_id;

  if (!tenantId) {
    const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
    res
      .status(errDef.statusCode)
      .json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INVALID_REQUEST,
          "Bad Request. Tenant context is missing."
        )
      );
    return;
  }

  req.tenant_id = tenantId;
  next();
};

// Middleware to verify if a tenant's active subscription includes access to a specific feature,
// and ensures they have not exceeded their usage quota for metered features.
export const requireEntitlement = (featureCode: string) => {
  return async (req: any, res: Response, next: NextFunction): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      // 1. Ensure the tenant context was properly set by requireTenant
      if (!tenantId) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "Tenant context is missing."
            )
          );
        return;
      }

      const now = new Date();

      // 2. Fetch the tenant's active subscription, including the specific requested feature
      // and any current usage records for the current billing period.
      const subscription = await prisma.subscription.findFirst({
        where: {
          tenantId: tenantId,
          status: "active"
        },
        include: {
          plan: {
            include: {
              planFeatures: {
                where: {
                  feature: {
                    feature_code: featureCode
                  }
                },
                include: {
                  feature: true
                }
              }
            }
          },
          subscriptionUsages: {
            where: {
              feature: {
                feature_code: featureCode
              },
              period_start: { lte: now },
              period_end: { gte: now }
            }
          }
        }
      });

      // 3. Reject if the tenant has no active subscription at all
      if (!subscription) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.SUBSCRIPTION_NOT_FOUND,
              "No active subscription found for this tenant."
            )
          );
        return;
      }

      const planFeature = subscription.plan.planFeatures[0];

      // 4. Reject if the requested feature is not included in their current plan
      if (!planFeature) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.FORBIDDEN,
              `Feature '${featureCode}' is not available on your current plan. Please upgrade.`
            )
          );
        return;
      }

      // 5. If the feature is metered ("limit"), verify they haven't exceeded their quota
      const feature = planFeature.feature;
      if (feature.type === "limit" && planFeature.limit_value !== null) {
        const usageRecord = subscription.subscriptionUsages[0];
        const currentUsage = usageRecord ? usageRecord.current_usage : 0;

        if (currentUsage >= planFeature.limit_value) {
          const errDef = ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_REQUIRED];
          // Pass the quota limit data strictly within the 'details' object so the frontend can render it
          res.status(errDef.statusCode).json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.PAYMENT_REQUIRED,
              {
                message: `You have reached your limit of ${planFeature.limit_value} for ${feature.name || featureCode}.`,
                current_usage: currentUsage,
                limit: planFeature.limit_value
              }
            )
          );
          return;
        }
      }

      // 6. Entitlement is valid and quota is available; proceed to controller
      next();
    } catch (error) {
      console.error(`Entitlement Check Error for [${featureCode}]:`, error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            "Internal server error verifying feature entitlement."
          )
        );
      return;
    }
  };
};
