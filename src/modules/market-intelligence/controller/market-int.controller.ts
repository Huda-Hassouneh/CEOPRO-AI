import { Response, NextFunction } from "express";
import * as marketIntelligenceService from "../service/market-int.service.js";
import { write } from "node:fs";

export const getMarketOverview = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const requestedPeriod = Number(req.query.periodDays ?? 30);
    const periodDays = [30, 90].includes(requestedPeriod)
      ? requestedPeriod
      : 30;
    const productId = req.query.productId
      ? String(req.query.productId)
      : undefined;
    const authorization = req.headers.authorization;

    const data = await marketIntelligenceService.getMarketIntelligence(
      tenantId,
      productId,
      periodDays,
      authorization
    );

    // Formatted strictly to { status, data } so httpClient unwraps cleanly.
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
