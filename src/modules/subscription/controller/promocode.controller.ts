import type { Response } from "express";
import {
  createPromocodeService,
  getPromocodeService,
  updatePromocodeService,
  validatePromoCode
} from "../service/promocodes.service.js";
import type { SuccessResponse } from "../../../types/response.js";
import type { AppRequest } from "../../../types/request.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";

export async function validatePromoHandler(req: AppRequest, resp: Response) {
  if (!req.tenant_id) {
    return sendApiError(resp, ERROR_CODES.UNAUTHORIZED);
  }

  const { code, planId } = req.body;
  const result = await validatePromoCode(code, planId, req.tenant_id);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Promo code is valid",
    data: result.data
  };
  return resp.status(200).json(response);
}

export async function patchPromocodeHandler(req: AppRequest, resp: Response) {
  const result = await updatePromocodeService(String(req.params.id), req.body);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Promocode updated successfully",
    data: result.data
  };
  return resp.status(200).json(response);
}

export async function getPromocodeHandler(_req: AppRequest, resp: Response) {
  const result = await getPromocodeService();
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Promocodes fetched successfully",
    data: result.data
  };
  return resp.status(200).json(response);
}

export async function postPromocodeHandler(req: AppRequest, resp: Response) {
  const result = await createPromocodeService(req.body);
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<typeof result.data> = {
    success: true,
    message: "Promocode created successfully",
    data: result.data
  };
  return resp.status(201).json(response);
}
