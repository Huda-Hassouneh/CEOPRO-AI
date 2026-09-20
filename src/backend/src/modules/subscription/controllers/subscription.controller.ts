import { Request, Response } from "express";
import {
  cancelSubscriptionService,
  checkoutService,
  getCurrentSubscriptionService,
  undoCancelSubscriptionService
} from "../service/subscription.service.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import { Subscription } from "../../../generated/prisma/client.js";

function handleError(resp: Response, code: string, customMessage?: string) {
  const safeCode = code as keyof typeof ERROR_DEFINITIONS;

  const errorDef = ERROR_DEFINITIONS[safeCode] || {
    message: customMessage || "An unexpected error occurred",
    statusCode: 400
  };

  const errorResponse: ErrorResponse = {
    success: false,
    error: {
      code: code,
      message: errorDef.message,
      statusCode: errorDef.statusCode
    }
  };

  return resp.status(errorDef.statusCode).json(errorResponse);
}

export async function checkoutHandler(req: any, resp: Response) {
  const userPayload = req.user;
  const result = await checkoutService(req.body, userPayload);

  if (!result.success) {
    return handleError(resp, result.code, result.message);
  }

  const response: SuccessResponse<{ checkoutUrl: string }> = {
    success: true,
    message: "Checkout session created successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function getCurrentSubscription(req: any, resp: Response) {
  const tenantId = req.tenant_id;
  const result = await getCurrentSubscriptionService(tenantId);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<Subscription> = {
    success: true,
    message: "Subscription fetched successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}
export async function patchCancelSubscriptionHandler(req: any, resp: Response) {
  const result = await cancelSubscriptionService(req.tenant_id);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Subscription cancellation scheduled successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function patchUndoCancelSubscriptionHandler(
  req: any,
  resp: Response
) {
  const result = await undoCancelSubscriptionService(req.tenant_id);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    message: "Subscription uncanceled successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}
