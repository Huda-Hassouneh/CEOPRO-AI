import { Request, Response } from "express";
import { planFeatureService } from "../service/plan-feature.service.js";
import { successResponse, errorResponse } from "../../../types/response.js"; // Adjust path
import { ERROR_CODES } from "../../../errors/error-codes.js"; // Adjust path
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js"; // Adjust path
import { featureRepository } from "../repo/plan-feature.repo.js";
import plansRepo from "../../subscription/repo/plans.repo.js";

export const planFeatureController = {
  linkFeature: async (req: any, res: Response): Promise<void> => {
    try {
      const { plan_id } = req.params;
      const { feature_id, limit_value } = req.body;

      const getFeature = await featureRepository.findFeatureById(feature_id);
      if (getFeature?.type === "boolean" && limit_value !== null) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_PARAMETER];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_PARAMETER,
              "A boolean feature cannot have a quota limit. Please set limit_value to null."
            )
          );
        return;
      }
      const getPlan = await plansRepo.getPlanById(plan_id);
      if (!getPlan) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.PLAN_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.PLAN_NOT_FOUND,
              "Plan not found"
            )
          );
        return;
      }

      // if()
      const linkedFeature = await planFeatureService.linkFeatureToPlan({
        plan_id,
        feature_id,
        limit_value: limit_value ?? null
      });

      res
        .status(201)
        .json(
          successResponse(linkedFeature, "Feature linked to plan successfully")
        );
    } catch (error: any) {
      if (error.message === ERROR_CODES.RESOURCE_ALREADY_EXISTS) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_ALREADY_EXISTS,
              "This feature is already linked to this plan."
            )
          );
        return;
      }

      console.error("Link Feature Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  },

  getForPlan: async (req: any, res: Response): Promise<void> => {
    try {
      const { plan_id } = req.params;
      const features = await planFeatureService.getPlanFeatures(plan_id);

      res
        .status(200)
        .json(
          successResponse(features, "Plan features retrieved successfully")
        );
    } catch (error: any) {
      console.error("Get Plan Features Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  },

  updateLimits: async (req: any, res: Response): Promise<void> => {
    try {
      const { plan_id, feature_id } = req.params;
      const { limit_value } = req.body;

      const getFeature = await featureRepository.findFeatureById(feature_id);
      if (getFeature?.type === "boolean" && limit_value !== null) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_PARAMETER];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_PARAMETER,
              "A boolean feature cannot have a quota limit. Please set limit_value to null."
            )
          );
        return;
      }
      const updated = await planFeatureService.updateFeatureLimits(
        plan_id,
        feature_id,
        limit_value
      );

      res
        .status(200)
        .json(successResponse(updated, "Limits updated successfully"));
    } catch (error: any) {
      if (error.message === ERROR_CODES.RESOURCE_NOT_FOUND) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_NOT_FOUND,
              "Feature link not found for this plan."
            )
          );
        return;
      }

      console.error("Update Limits Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};
