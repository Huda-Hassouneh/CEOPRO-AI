import type { Response } from "express";
import { webhookService } from "./webhook.service.js";
import type { AppRequest } from "../../../../../types/request.js";
import { ERROR_CODES } from "../../../../../errors/error-codes.js";
import { sendApiError } from "../../../../../utils/http.js";

export async function webhookHandler(req: AppRequest, resp: Response) {
  if (!req.stripeEvent) {
    return sendApiError(resp, ERROR_CODES.INVALID_WEBHOOK_HEADER);
  }

  const result = await webhookService(req.stripeEvent);

  if (!result.success) {
    // A non-2xx response instructs Stripe to retry; keep internal errors out
    // of the response body.
    return sendApiError(resp, ERROR_CODES.WEBHOOK_PROCESSING_ERROR);
  }

  return resp.status(200).json({
    received: true,
    duplicate: result.data.duplicate
  });
}
