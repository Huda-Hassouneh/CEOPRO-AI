import { Router } from "express";
import {
  getPlansHndler,
  getPromocodeHandler,
  linkPlanWithPromocodeHandler,
  patchPlanHandler,
  patchPromocodeHandler,
  postPlanHandler,
  postPromocodeHandler,
  validatePromoHandler
} from "./controller.js";
import {
  isAdmin,
  validateHeader,
  validateToken
} from "../../validators/token.js";
import { validateBody } from "../../validators/validateBody.js";
import {
  applyPromoCodeSchema,
  createPromoCodeSchema,
  promoCodePlanParamsSchema,
  updatePromoCodeSchema
} from "../../DTO/promoCode.dto.js";
import {
  planParamsSchema,
  planSchema,
  updatePlanSchema
} from "../../DTO/plan.dto.js";
import { validateParams } from "../../validators/validateParams.js";

const router = Router();

// global - route-scoped middlewares -
router.use(validateHeader, validateToken, isAdmin);

router.get("/plans", getPlansHndler);
router.get("/promo-codes", getPromocodeHandler);

router.post(
  "/promo-codes/:promoCodeId/plans/:planId",
  validateParams(promoCodePlanParamsSchema),
  linkPlanWithPromocodeHandler
);
router.post("/plans", validateBody(planSchema), postPlanHandler);
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

router.patch(
  "/promo-codes/:id",
  validateBody(updatePromoCodeSchema),
  validateParams(planParamsSchema),

  patchPromocodeHandler
);
router.patch(
  "/plans/:id",
  validateBody(updatePlanSchema),
  validateParams(planParamsSchema),
  patchPlanHandler
);

export default { router };
