import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import { isPricingClientError } from "../client/pricing.client.js";
import {
  getPricingRecommendation,
  isPricingServiceError
} from "../service/pricing.service.js";

export async function recommendPrice(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const authorization = req.headers.authorization;
    const productId =
      typeof req.query.product_id === "string" ? req.query.product_id : null;

    if (!tenantId || !userId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    if (!authorization) {
      sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
      return;
    }

    if (!productId) {
      sendApiError(res, ERROR_CODES.INVALID_PARAMETER);
      return;
    }

    const data = await getPricingRecommendation({
      tenantId,
      userId,
      productId
    });

    res
      .status(200)
      .json(
        successResponse(data, "Pricing recommendation fetched successfully")
      );
  } catch (error) {
    if (isPricingServiceError(error)) {
      if (error.code === "PRODUCT_NOT_FOUND") {
        sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND, {
          publicMessage: "Product not found"
        });
        return;
      }
    }

    if (isPricingClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI pricing service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }

    next(error);
  }
}
