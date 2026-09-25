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
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../validators/validatePlatformUser.js";

const router = Router();

router.use(authenticateUser);

router.get("/", requirePlatformRole, requirePlatformPermission("billing.read"), getPromocodeHandler);

router.post(
  "/",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateBody(createPromoCodeSchema),
  postPromocodeHandler
);

router.post(
  "/validate",
  requireTenant,
  requirePermission("manage_billing"), // Tenant billing permission
  validateBody(applyPromoCodeSchema),
  validatePromoHandler
);

router.patch(
  "/:id",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(planParamsSchema), // *Consider renaming this DTO to promoCodeParamsSchema!*
  validateBody(updatePromoCodeSchema),
  patchPromocodeHandler
);

router.post(
  "/:promoCodeId/plans/:planId",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(promoCodePlanParamsSchema),
  linkPlanWithPromocodeHandler
);

export default router;
