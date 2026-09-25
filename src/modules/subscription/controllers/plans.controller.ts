import type { Request, Response } from "express";
import {
  changePlanService,
  createPlansService,
  updatePlansService,
  getPlans
} from "../service/plans.service.js";
import type { SuccessResponse } from "../../../types/response.js";
import type { AppRequest } from "../../../types/request.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";

export async function getPlansHandler(_req: Request, resp: Response) {
  try {
    const plans = await getPlans();
    const response: SuccessResponse<typeof plans> = {
      success: true,
      message: "Plans retrieved successfully",
      data: plans
    };
    return resp.status(200).json(response);
  } catch (error) {
    console.error("Error retrieving subscription plans:", error);
    return sendApiError(resp, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export async function postPlanHandler(req: Request, resp: Response) {
  const result = await createPlansService(req.body);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Plan created successfully",
    data: result.data
  };
  return resp.status(201).json(response);
}

export async function changePlanHandler(req: AppRequest, resp: Response) {
  if (!req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  try {
    const { planId, billing_period } = req.body;
    const result = await changePlanService(planId, req.tenant_id, billing_period);

    if (!result.success) {
      return sendApiError(resp, result.code);
    }

    const response: SuccessResponse<null> = {
      success: true,
      message: result.message || "Subscription updated successfully",
      data: null
    };
    return resp.status(200).json(response);
  } catch (error) {
    console.error("[changePlanHandler Error]:", error);
    return sendApiError(resp, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export async function patchPlanHandler(req: Request, resp: Response) {
  const result = await updatePlansService(String(req.params.id), req.body);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Plan updated successfully",
    data: result.data
  };
  return resp.status(200).json(response);
}
