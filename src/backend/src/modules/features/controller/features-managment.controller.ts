import { Request, Response } from "express";
import { featureService } from "../service/features.service.js";
import { successResponse, errorResponse } from "../../../types/response.js"; // Adjust path
import { ERROR_CODES } from "../../../errors/error-codes.js"; // Adjust path
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js"; // Adjust path

export const featureController = {
  create: async (req: Request, res: Response): Promise<void> => {
    try {
      const {
        code,
        name,
        description,
        type,
        aggregationType,
        description_ar,
        name_ar
      } = req.body;

      const feature = await featureService.createFeature({
        code,
        name,
        description,
        type,
        name_ar,
        description_ar,
        aggregationType
      });

      res
        .status(201)
        .json(successResponse(feature, "Feature created successfully"));
    } catch (error: any) {
      if (
        error.message === ERROR_CODES.RESOURCE_ALREADY_EXISTS ||
        error.message.includes("already exists")
      ) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_ALREADY_EXISTS,
              error.message
            )
          );
      } else {
        console.error("Create Feature Error:", error);
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
  },

  getAll: async (req: Request, res: Response): Promise<void> => {
    try {
      const features = await featureService.getAllFeatures();
      res
        .status(200)
        .json(successResponse(features, "Features retrieved successfully"));
    } catch (error) {
      console.error("Get All Features Error:", error);
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

  getOne: async (req: any, res: Response): Promise<void> => {
    try {
      const { id } = req.params;
      const feature = await featureService.getFeatureById(id);

      res
        .status(200)
        .json(successResponse(feature, "Feature retrieved successfully"));
    } catch (error: any) {
      if (
        error.message === ERROR_CODES.RESOURCE_NOT_FOUND ||
        error.message === "Feature not found."
      ) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_NOT_FOUND,
              "The requested feature could not be found."
            )
          );
      } else {
        console.error("Get Feature Error:", error);
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
  },

  update: async (req: any, res: Response): Promise<void> => {
    try {
      const { id } = req.params;
      const {
        name,
        description,
        type,
        aggregation_type: aggregationType,
        reset_cycle,

        unit
      } = req.body;

      // Note: We intentionally do not allow updating the feature_code once created
      // to prevent breaking existing plan associations.
      const updatedFeature = await featureService.updateFeature(id, {
        name,
        description,
        type,
        aggregationType,
        resetCycle: reset_cycle,
        unit
      });

      res
        .status(200)
        .json(successResponse(updatedFeature, "Feature updated successfully"));
    } catch (error: any) {
      if (
        error.message === ERROR_CODES.RESOURCE_NOT_FOUND ||
        error.message === "Feature not found."
      ) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_NOT_FOUND,
              "The feature you are trying to update does not exist."
            )
          );
      } else {
        console.error("Update Feature Error:", error);
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
  }
};
