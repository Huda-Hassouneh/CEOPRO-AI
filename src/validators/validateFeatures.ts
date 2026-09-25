import { Response, NextFunction } from "express";
import { errorResponse } from "../types/response.js";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-definitions.js";
import {
  getFeatureAccessInfo,
  getRemainingUsage
} from "../modules/features/repo/usage.repo.js";
import { getConsumptionBlockReason } from "../modules/features/service/entitlement-policy.js";

function respondMissingSubscription(res: Response) {
  const errDef = ERROR_DEFINITIONS[ERROR_CODES.SUBSCRIPTION_NOT_FOUND];
  res.status(errDef.statusCode).json(
    errorResponse(
      errDef.message,
      errDef.statusCode,
      ERROR_CODES.SUBSCRIPTION_NOT_FOUND,
      { reason: "NO_ACTIVE_SUBSCRIPTION" }
    )
  );
}

function respondFeatureNotIncluded(res: Response, featureCode: string) {
  const errDef = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];
  res.status(errDef.statusCode).json(
    errorResponse(errDef.message, errDef.statusCode, ERROR_CODES.FORBIDDEN, {
      feature_code: featureCode,
      reason: "FEATURE_NOT_INCLUDED"
    })
  );
}

export const requireFeatureAccess = (featureCode: string) => {
  return async (req: any, res: Response, next: NextFunction): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      if (!tenantId) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INVALID_REQUEST,
            "Tenant context is missing."
          )
        );
        return;
      }

      const { subscription, planFeature } = await getFeatureAccessInfo(
        tenantId,
        featureCode
      );
      if (!subscription) return respondMissingSubscription(res);
      if (!planFeature) return respondFeatureNotIncluded(res, featureCode);
      next();
    } catch (error) {
      console.error(`Feature access check error for [${featureCode}]:`, error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  };
};

export const requireEntitlement = (featureCode: string) => {
  return async (req: any, res: Response, next: NextFunction): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      if (!tenantId) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INVALID_REQUEST,
            "Tenant context is missing."
          )
        );
        return;
      }

      const { subscription, planFeature } = await getFeatureAccessInfo(
        tenantId,
        featureCode
      );
      if (!subscription) return respondMissingSubscription(res);
      if (!planFeature) return respondFeatureNotIncluded(res, featureCode);

      const entitlement = await getRemainingUsage(tenantId, featureCode);
      if (!entitlement) return respondFeatureNotIncluded(res, featureCode);

      const blockReason = getConsumptionBlockReason({
        included: true,
        isUnlimited: entitlement.isUnlimited,
        isExceeded: entitlement.isExceeded,
        aggregationType: entitlement.aggregationType
      });

      if (blockReason) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_REQUIRED];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.PAYMENT_REQUIRED,
            {
              feature_code: featureCode,
              reason: blockReason,
              current_usage: entitlement.currentUsage,
              limit: entitlement.limit,
              remaining: 0,
              aggregation_type: entitlement.aggregationType,
              reset_cycle: entitlement.resetCycle,
              period_end: entitlement.periodEnd
            }
          )
        );
        return;
      }

      next();
    } catch (error) {
      console.error(`Entitlement check error for [${featureCode}]:`, error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  };
};
