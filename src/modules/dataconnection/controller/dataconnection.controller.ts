import { Request, Response, NextFunction } from "express";
import * as dataConnectionsService from "../service/dataconnection.service.js";

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
