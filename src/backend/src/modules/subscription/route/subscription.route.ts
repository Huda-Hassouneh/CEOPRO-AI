import { Router } from "express";
import {
  checkoutHandler,
  patchCancelSubscriptionHandler,
  patchUndoCancelSubscriptionHandler
} from "../controllers/subscription.route.js";
import { changePlanHandler } from "../controllers/plans.controller.js";
import { validateBody } from "../../../validators/validateBody.js";

import { checkoutSchema } from "../../../DTO/checkout.dto.js";
import { changePlanSchema } from "../../../DTO/changePlan.dto.js";

const router = Router();

router.patch("/cancel", patchCancelSubscriptionHandler);
router.patch("/cancel/undo", patchUndoCancelSubscriptionHandler);
router.post("/change-plan", validateBody(changePlanSchema), changePlanHandler);
router.post("/checkout", validateBody(checkoutSchema), checkoutHandler);
export default { router };
