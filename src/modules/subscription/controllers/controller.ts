import type { Request, Response } from "express";
import { onBoardingService } from "../service/service.js";
import { configKeys } from "../../../config/keys.config.js";
import type { SuccessResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";

export async function onBoardingHandler(_req: Request, resp: Response) {
  const result = await onBoardingService();
  if (!result.success) {
    return sendApiError(resp, result.code);
  }

  const response: SuccessResponse<null> = {
    success: true,
    data: result.data,
    message: `${configKeys.stripeAppConfigKey} inserted successfully.`
  };

  return resp.status(201).json(response);
}
