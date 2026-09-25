import { Request, Response } from "express";
import { featureService } from "../service/features.service.js";
import { successResponse, errorResponse } from "../../../types/response.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";

export const featureController = {
  create: async (req: Request, res: Response): Promise<void> => {
    try {
      const {
        code,
        name,
        name_ar,
        description,
        description_ar,
        type,
        unit,
        unit_ar,
        aggregation_type: aggregationType,
        reset_cycle: resetCycle
      } = req.body;

      const feature = await featureService.createFeature({
        code,
        name,
        name_ar,
        description,
        description_ar,
        type,
        unit,
        unit_ar,
        aggregationType,
        resetCycle
      });

      res.status(201).json(successResponse(feature, "Feature created successfully"));
    } catch (error: any) {
      if (
        error.message === ERROR_CODES.RESOURCE_ALREADY_EXISTS ||
        error.message?.includes("already exists")
      ) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.RESOURCE_ALREADY_EXISTS,
            error.message
          )
        );
        return;
      }

      console.error("Create Feature Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  },

  getAll: async (_req: Request, res: Response): Promise<void> => {
    try {
      const features = await featureService.getAllFeatures();
      res.status(200).json(successResponse(features, "Features retrieved successfully"));
    } catch (error) {
      console.error("Get All Features Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  },

  getOne: async (req: any, res: Response): Promise<void> => {
    try {
      const feature = await featureService.getFeatureById(req.params.id);
      res.status(200).json(successResponse(feature, "Feature retrieved successfully"));
    } catch (error: any) {
      if (error.message === ERROR_CODES.RESOURCE_NOT_FOUND) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.RESOURCE_NOT_FOUND,
            "The requested feature could not be found."
          )
        );
        return;
      }

      console.error("Get Feature Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  },

  update: async (req: any, res: Response): Promise<void> => {
    try {
      const {
        name,
        name_ar,
        description,
        description_ar,
        type,
        aggregation_type: aggregationType,
        reset_cycle: resetCycle,
        unit,
        unit_ar
      } = req.body;

      const updatedFeature = await featureService.updateFeature(req.params.id, {
        name,
        name_ar,
        description,
        description_ar,
        type,
        aggregationType,
        resetCycle,
        unit,
        unit_ar
      });

      res.status(200).json(successResponse(updatedFeature, "Feature updated successfully"));
    } catch (error: any) {
      if (error.message === ERROR_CODES.RESOURCE_NOT_FOUND) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.RESOURCE_NOT_FOUND,
            "The feature you are trying to update does not exist."
          )
        );
        return;
      }

      console.error("Update Feature Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res.status(errDef.statusCode).json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR
        )
      );
    }
  }
};
