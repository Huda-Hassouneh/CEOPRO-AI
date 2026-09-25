import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../errors/error-codes.js";
import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";
import type { AppRequest } from "../types/request.js";
import { sendApiError } from "../utils/http.js";

export default function validateWebhook(
  req: AppRequest,
  res: Response,
  next: NextFunction
) {
  const signature = req.headers["stripe-signature"];
  if (typeof signature !== "string" || signature.length === 0) {
    return sendApiError(res, ERROR_CODES.INVALID_WEBHOOK_HEADER);
  }

  const webhookSecret = process.env.STRIPE_SECRET_WEBHOOK?.trim();
  if (!webhookSecret) {
    console.error("STRIPE_SECRET_WEBHOOK is not configured");
    return sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }

  try {
    req.stripeEvent = stripeService.stripe.webhooks.constructEvent(
      req.body,
      signature,
      webhookSecret
    );
    next();
  } catch {
    return sendApiError(res, ERROR_CODES.INVALID_WEBHOOK_HEADER);
  }
}
