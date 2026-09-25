import { Router } from "express";
import {
  getPlansHandler,
  patchPlanHandler,
  postPlanHandler
} from "../controllers/plans.controller.js";

import { validateBody } from "../../../validators/validateBody.js";
import { validateParams } from "../../../validators/validateParams.js";

import {
  planParamsSchema,
  planSchema,
  updatePlanSchema
} from "../../../DTO/plan.dto.js";

// Import your security middlewares
import { authenticateUser } from "../../../validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../validators/validatePlatformUser.js";

const router = Router();

router.get("/", getPlansHandler);

router.post(
  "/",
  authenticateUser,
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateBody(planSchema),
  postPlanHandler
);

router.patch(
  "/:id",
  authenticateUser,
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(planParamsSchema),
  validateBody(updatePlanSchema),
  patchPlanHandler
);

export default router;
