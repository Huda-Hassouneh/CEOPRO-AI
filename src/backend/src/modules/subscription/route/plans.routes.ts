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
import {
  authenticateUser,
  requireTenant,
  requirePermission
} from "../../../validators/validateUser.js";

const router = Router();

router.get("/", getPlansHandler);

router.post(
  "/",
  authenticateUser,
  requireTenant,
  requirePermission("all"), // Requires catalog management rights
  validateBody(planSchema),
  postPlanHandler
);

router.patch(
  "/:id",
  authenticateUser,
  requireTenant,
  requirePermission("all"),
  validateParams(planParamsSchema),
  validateBody(updatePlanSchema),
  patchPlanHandler
);

export default router;
