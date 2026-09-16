import { Router } from "express";
import { linkPlanWithPromocodeHandler } from "../controllers/promocodes-plans..controller.js";

import { promoCodePlanParamsSchema } from "../../../DTO/promoCode.dto.js";

import { validateParams } from "../../../validators/validateParams.js";
const router = Router();

router.post(
  "/promo-codes/:promoCodeId/plans/:planId",
  validateParams(promoCodePlanParamsSchema),
  linkPlanWithPromocodeHandler
);
export default { router };
