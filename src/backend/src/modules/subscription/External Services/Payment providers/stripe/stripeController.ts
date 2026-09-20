import { Response } from "express";
import { webhookService } from "./webhook.service.js";

export async function webhookHandler(req: any, resp: Response) {
  const result = await webhookService(req.stripeEvent);

  if (!result.success) {
    // If the service failed, we MUST return a non-200 status code.
    // This signals to Stripe that they should retry this webhook later.
    return resp.status(500).json({
      success: false,
      error: result.message
    });
  }

  return resp.status(200).json({
    received: true,
    duplicate: result.data.duplicate
  });
}
