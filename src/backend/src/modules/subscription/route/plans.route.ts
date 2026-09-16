import { Router } from "express";
import {
  getPlansHndler,
  patchPlanHandler,
  postPlanHandler
} from "../controllers/plans.controller.js";

import { validateBody } from "../../../validators/validateBody.js";

import {
  planParamsSchema,
  planSchema,
  updatePlanSchema
} from "../../../DTO/plan.dto.js";
import { validateParams } from "../../../validators/validateParams.js";
const router = Router();

router.get("/plans", getPlansHndler);
router.post("/plans", validateBody(planSchema), postPlanHandler);

router.patch(
  "/plans/:id",
  validateBody(updatePlanSchema),
  validateParams(planParamsSchema),
  patchPlanHandler
);
export default { router };
