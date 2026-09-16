import { NextFunction, Request, Response } from "express";
import Stripe from "stripe";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-defentions.js";
import { ErrorResponse } from "../types/response.js";
import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";

export default function validateWebhook(
  req: any,
  resp: Response,
  next: NextFunction
) {
  const signature = req.headers["stripe-signature"];
  const stripe = stripeService.stripe;
  try {
    const event = stripe.webhooks.constructEvent(
      req.body,
      signature!,
      process.env.STRIPE_SECRET_WEBHOOK!
    );

    req.stripeEvent = event;
    // handle event...

    next();
  } catch (error) {
    console.error("Webhook verification failed:", error);

    return resp
      .status(ERROR_DEFINITIONS[ERROR_CODES.INVALID_WEBHOOK_HEADER].statusCode)
      .json({
        success: false,
        error: {
          message:
            ERROR_DEFINITIONS[ERROR_CODES.INVALID_WEBHOOK_HEADER].message,
          statusCode:
            ERROR_DEFINITIONS[ERROR_CODES.INVALID_WEBHOOK_HEADER].statusCode,
          code: ERROR_CODES.INVALID_WEBHOOK_HEADER
        }
      } as ErrorResponse);
  }
}
