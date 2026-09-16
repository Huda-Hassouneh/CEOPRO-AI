import { Router } from "express";
import {
  getPromocodeHandler,
  patchPromocodeHandler,
  postPromocodeHandler,
  validatePromoHandler
} from "../controllers/promocode.controller.js";

import { validateBody } from "../../../validators/validateBody.js";
import {
  applyPromoCodeSchema,
  createPromoCodeSchema,
  updatePromoCodeSchema
} from "../../../DTO/promoCode.dto.js";
import { planParamsSchema } from "../../../DTO/plan.dto.js";
import { validateParams } from "../../../validators/validateParams.js";

const router = Router();
router.get("/promo-codes", getPromocodeHandler);
router.patch(
  "/promo-codes/:id",
  validateBody(updatePromoCodeSchema),
  validateParams(planParamsSchema),

  patchPromocodeHandler
);
router.post(
  "/validate-promo-code",
  validateBody(applyPromoCodeSchema),
  validatePromoHandler
);
router.post(
  "/promo-codes",
  validateBody(createPromoCodeSchema),
  postPromocodeHandler
);
export default { router };
