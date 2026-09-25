import { Request, Response, NextFunction } from "express";
import * as forecastingService from "../service/forecasting.service.js";

export const getOverview = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const periodDays = req.query.periodDays
      ? parseInt(req.query.periodDays as string, 10)
      : 30;
    const productId = req.query.productId ? String(req.query.productId) : "all";

    const data = await forecastingService.getDemandOverview(
      tenantId,
      periodDays,
      productId
    );
    console.log(JSON.stringify(data));

    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};

export const getDetail = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const productId = req.params.productId as string;

    const data = await forecastingService.getDemandDetail(tenantId, productId);

    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
