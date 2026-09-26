import { Request, Response, NextFunction } from "express";
import * as dataConnectionsService from "../service/dataconnection.service.js";
import { AppRequest } from "../../../types/request.js";
import { dataManagementRepo } from "../repo/dataconnection.repo.js";
import { errorResponse, successResponse } from "../../../types/response.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";

export const getConnectionsOverview = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;

    const data =
      await dataConnectionsService.getDataConnectionsOverview(tenantId);

    return res.status(200).json({
      status: "success",
      data
    });
  } catch (error) {
    next(error);
  }
};

export const activityController = {
  getRecentDataActivity: async (
    req: AppRequest,
    res: Response
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id as string;
      const limit = parseInt(req.query.limit as string) || 10;

      const recentActivity = await dataManagementRepo.getRecentActivity(
        tenantId,
        limit
      );

      res
        .status(200)
        .json(
          successResponse(
            recentActivity,
            "Recent activity fetched successfully"
          )
        );
    } catch (error) {
      console.error("Activity Controller Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  }
};
