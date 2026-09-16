import { Request, Response } from "express";
import {
  cancelSubscriptionService,
  checkoutService,
  undoCancelSubscriptionService
} from "../service/subscription.service.js";
export async function checkoutHandler(req: any, resp: Response) {
  const userPayload = req.user;
  const result = await checkoutService(req.body, userPayload);
  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(200).json(result);
}
export async function patchCancelSubscriptionHandler(
  req: Request,
  resp: Response
) {
  const result = await cancelSubscriptionService();

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(200).json(result);
}
export async function patchUndoCancelSubscriptionHandler(
  req: Request,
  resp: Response
) {
  const result = await undoCancelSubscriptionService();

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(200).json(result);
}
