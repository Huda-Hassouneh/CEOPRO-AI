import type { Response } from "express";
import {
  cancelSubscriptionService,
  checkoutService,
  getCurrentSubscriptionService,
  undoCancelSubscriptionService
} from "../service/subscription.service.js";
import type { SuccessResponse } from "../../../types/response.js";
import type { Subscription } from "../../../generated/prisma/client.js";
import type { AppRequest } from "../../../types/request.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";

export async function checkoutHandler(req: AppRequest, resp: Response) {
  if (!req.user || !req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  const result = await checkoutService(req.body, {
    email: req.user.email,
    id: req.user.id,
    tenant_id: req.tenant_id
  });

  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<{ checkoutUrl: string }> = {
    success: true,
    message: "Checkout session created successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function getCurrentSubscription(req: AppRequest, resp: Response) {
  if (!req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  const result = await getCurrentSubscriptionService(req.tenant_id);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<Subscription> = {
    success: true,
    message: "Subscription fetched successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function patchCancelSubscriptionHandler(
  req: AppRequest,
  resp: Response
) {
  if (!req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  const result = await cancelSubscriptionService(req.tenant_id);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Subscription cancellation scheduled successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function patchUndoCancelSubscriptionHandler(
  req: AppRequest,
  resp: Response
) {
  if (!req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  const result = await undoCancelSubscriptionService(req.tenant_id);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Subscription uncanceled successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}
