import type { Response, NextFunction } from "express";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import * as forecastingService from "../service/forecasting.service.js";
import { isForecastingClientError } from "../client/forecasting.client.js";
import { forecastGenerationBodySchema } from "../types/forecasting.validation.js";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function parseForecastQuery(
  period: unknown,
  product: unknown,
  allowAll = true
) {
  const periodDays =
    period === undefined
      ? 30
      : period === "7"
        ? 7
        : period === "30"
          ? 30
          : null;
  const productId = product === undefined && allowAll ? "all" : product;
  return periodDays &&
    typeof productId === "string" &&
    ((allowAll && productId === "all") || uuid.test(productId))
    ? { periodDays, productId }
    : null;
}
const respond = async (
  req: AppRequest,
  res: Response,
  next: NextFunction,
  detail: boolean
) => {
  try {
    if (!req.tenant_id || !req.user?.user_id)
      return sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
    const params = parseForecastQuery(
      req.query.periodDays,
      detail ? req.params.productId : req.query.productId,
      !detail
    );
    if (!params) return sendApiError(res, ERROR_CODES.INVALID_PARAMETER);
    const data = detail
      ? await forecastingService.getDemandDetail(
          req.tenant_id,
          params.productId,
          req.user.id,
          params.periodDays
        )
      : await forecastingService.getDemandOverview(
          req.tenant_id,
          params.periodDays,
          params.productId,
          req.user.id
        );
    if (!data) return sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND);
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
export const getOverview = (
  req: AppRequest,
  res: Response,
  next: NextFunction
) => respond(req, res, next, false);
export const getDetail = (req: AppRequest, res: Response, next: NextFunction) =>
  respond(req, res, next, true);

export async function generateDemand(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    if (!tenantId || !userId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    const productId = Array.isArray(req.params.productId)
      ? req.params.productId[0]
      : req.params.productId;
    if (!productId || !uuid.test(productId)) {
      sendApiError(res, ERROR_CODES.INVALID_PARAMETER, {
        details: {
          field: "productId",
          message: "productId must be a valid UUID."
        }
      });
      return;
    }

    const parsedBody = forecastGenerationBodySchema.safeParse(
      req.body === undefined ? {} : req.body
    );
    if (!parsedBody.success) {
      sendApiError(res, ERROR_CODES.INVALID_PARAMETER, {
        details: {
          issues: parsedBody.error.issues.map((issue) => ({
            field: issue.path.join("."),
            message: issue.message
          }))
        }
      });
      return;
    }

    const { horizon_days: horizonDays } = parsedBody.data;
    const data = await forecastingService.generateDemandForecast({
      tenantId,
      userId,
      productId,
      horizonDays
    });
    if (!data) {
      sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND);
      return;
    }
    res.status(200).json({ status: "success", data });
  } catch (error) {
    if (isForecastingClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI forecasting service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }
    next(error);
  }
}
