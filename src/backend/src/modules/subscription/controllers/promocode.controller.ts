import { Request, Response } from "express";
import {
  createPromocodeService,
  getPromocodeService,
  updatePromocodeService,
  validatePromoCode
} from "../service/promocodes.service.js";
import { ErrorResponse, SuccessResponse } from "../../../types/response.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
function handleError(resp: Response, code: string) {
  const safeCode = code as keyof typeof ERROR_DEFINITIONS;
  const errorDef = ERROR_DEFINITIONS[safeCode] || {
    message: "An unexpected error occurred",
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

export async function validatePromoHandler(req: Request, resp: Response) {
  const { code, plan } = req.body;
  const result = await validatePromoCode(code, plan);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Promo code is valid",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function patchPromocodeHandler(req: Request, resp: Response) {
  const id: string = req.params.id as string;
  const result = await updatePromocodeService(id, req.body);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Promocode updated successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function getPromocodeHandler(req: Request, resp: Response) {
  const result = await getPromocodeService();

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Promocodes fetched successfully",
    data: result.data
  };

  return resp.status(200).json(response);
}

export async function postPromocodeHandler(req: Request, resp: Response) {
  const result = await createPromocodeService(req.body);

  if (!result.success) {
    return handleError(resp, result.code);
  }

  const response: SuccessResponse<any> = {
    success: true,
    message: "Promocode created successfully",
    data: result.data
  };

  return resp.status(201).json(response);
}
