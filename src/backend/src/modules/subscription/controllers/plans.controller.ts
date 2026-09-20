import { Request, Response } from "express";
import {
  changePlanService,
  createPlansService,
  getPlansService,
  updatePlansService,
  getPlans
} from "../service/plans.service.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";

function handleError(resp: Response, code: string, customMessage?: string) {
  // Fallback definitions in case the code isn't in ERROR_DEFINITIONS yet
  const safeCode = code as keyof typeof ERROR_DEFINITIONS;
  const errorDef = ERROR_DEFINITIONS[safeCode] || {
    message: customMessage || "An error occurred",
    statusCode: code === "UNPROCESSABLE_ENTITY" ? 422 : 400
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

export async function getPlansHandler(req: Request, resp: Response) {
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
    return resp.status(500).json({
      success: false,
      message: "An internal server error occurred while retrieving plans",
      data: []
    });
  }
}

export async function postPlanHandler(req: Request, resp: Response) {
  const result = await createPlansService(req.body);

  if (!result.success) {
    return handleError(resp, result.code, result.message);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Plan created successfully",
    data: result.data
  };

  return resp.status(201).json(response);
}

export async function changePlanHandler(req: any, resp: Response) {
  try {
    const { planId, billing_period } = req.body;

    // 1. Basic input validation
    if (!planId || !billing_period) {
      return handleError(
        resp,
        "VALIDATION_ERROR",
        "planId and billing_period are required."
      );
    }

    const result = await changePlanService(
      planId,
      req.tenant_id,
      billing_period
    );

    if (!result.success) {
      // 2. Handle NOT_FOUND gracefully
      if (
        result.code === "SUBSCRIPTION_NOT_FOUND" ||
        result.code === "PLAN_NOT_FOUND"
      ) {
        const errorResponse = {
          success: false,
          error: {
            code: result.code,
            message:
              result.message || "Tenant does not have an active subscription",
            statusCode: 404
          }
        };
        return resp.status(404).json(errorResponse);
      }

      // 3. Pass the dynamic error message to your handler (so the UI sees "You are already scheduled...")
      return handleError(resp, result.code, result.message);
    }

    // 4. Use the dynamic success message from the service (Upgrade vs Scheduled Downgrade)
    const response = {
      success: true,
      message: result.message || "Subscription updated successfully",
      data: null
    };

    // 5. Change 201 (Created) to 200 (OK) since we are updating an existing subscription
    return resp.status(200).json(response);
  } catch (error: any) {
    console.error("[changePlanHandler Error]:", error);
    return handleError(
      resp,
      "INTERNAL_SERVER_ERROR",
      "An unexpected error occurred while changing the plan."
    );
  }
}

export async function patchPlanHandler(req: Request, resp: Response) {
  const id: string = req.params.id as string;
  const result = await updatePlansService(id, req.body);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Plan updated successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}
