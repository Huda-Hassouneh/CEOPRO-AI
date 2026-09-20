import { Router } from "express";
import {
  getPromocodeHandler,
  patchPromocodeHandler,
  postPromocodeHandler,
  validatePromoHandler
} from "../controllers/promocode.controller.js";
import { linkPlanWithPromocodeHandler } from "../controllers/promocodes-plans..controller.js";

import { validateBody } from "../../../validators/validateBody.js";
import { validateParams } from "../../../validators/validateParams.js";

import {
  applyPromoCodeSchema,
  createPromoCodeSchema,
  updatePromoCodeSchema,
  promoCodePlanParamsSchema
} from "../../../DTO/promoCode.dto.js";
import { planParamsSchema } from "../../../DTO/plan.dto.js";

import {
  authenticateUser,
  requireTenant,
  requirePermission
} from "../../../validators/validateUser.js";

const router = Router();

router.use(authenticateUser);
router.use(requireTenant);

router.get("/", requirePermission("all"), getPromocodeHandler);

router.post(
  "/",
  requirePermission("all"),
  validateBody(createPromoCodeSchema),
  postPromocodeHandler
);

router.post(
  "/validate",
  requirePermission("manage_billing"), // Allow tenants managing their billing to validate codes
  validateBody(applyPromoCodeSchema),
  validatePromoHandler
);

router.patch(
  "/:id",
  requirePermission("manage_catalog"),
  validateParams(planParamsSchema), // *Consider renaming this DTO to promoCodeParamsSchema!*
  validateBody(updatePromoCodeSchema),
  patchPromocodeHandler
);

router.post(
  "/:promoCodeId/plans/:planId",
  requirePermission("all"),
  validateParams(promoCodePlanParamsSchema),
  linkPlanWithPromocodeHandler
);

export default router;
