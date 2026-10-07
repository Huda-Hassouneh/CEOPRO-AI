import type { Response, NextFunction } from "express";
import * as marketIntelligenceService from "../service/market-int.service.js";
import type { AppRequest } from "../../../types/request.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";

export const getMarketOverview = async (
  req: AppRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const requestedPeriod = Number(req.query.periodDays ?? 30);
    const periodDays = [30, 90].includes(requestedPeriod)
      ? requestedPeriod
      : 30;
    const productId = req.query.productId
      ? String(req.query.productId)
      : undefined;
    if (!tenantId || !userId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    const data = await marketIntelligenceService.getMarketIntelligence(
      tenantId,
      userId,
      productId,
      periodDays
    );

    // Formatted strictly to { status, data } so httpClient unwraps cleanly.
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
