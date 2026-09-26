import { Request, Response, NextFunction } from "express";
import * as marketIntelligenceService from "../service/market-int.service.js";

export const getMarketOverview = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const periodDays = req.query.periodDays
      ? parseInt(req.query.periodDays as string, 10)
      : 30;
    const productId = req.query.productId
      ? String(req.query.productId)
      : undefined;
    console.log({ tenantId, periodDays, productId });

    const data = await marketIntelligenceService.getMarketIntelligence(
      tenantId,
      productId,
      periodDays
    );

    // Formatted strictly to { status, data } so httpClient unwraps cleanly
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
