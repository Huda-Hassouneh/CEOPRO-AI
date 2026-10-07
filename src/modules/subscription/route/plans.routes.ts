import { Router } from "express";
import {
  getPlansHandler,
  patchPlanHandler,
  postPlanHandler
} from "../controller/plans.controller.js";

import { validateBody } from "../../../middleware/validators/validateBody.js";
import { validateParams } from "../../../middleware/validators/validateParams.js";

import {
  planParamsSchema,
  planSchema,
  updatePlanSchema
} from "../../../DTO/plan.dto.js";

// Import your security middlewares
import { authenticateUser } from "../../../middleware/validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../middleware/validators/validatePlatformUser.js";

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
