import { Request, Response } from "express";
import { linkPromoCodePlan } from "../service/promocodes-plans.service.js";
export async function linkPlanWithPromocodeHandler(
  req: Request,
  resp: Response
) {
  const planId: string = req.params.planId as string;
  const promoCodeId: string = req.params.promoCodeId as string;
  // console.log(planId, promoCodeId);

  const result = await linkPromoCodePlan(planId, promoCodeId);

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(201).json(result);
}
