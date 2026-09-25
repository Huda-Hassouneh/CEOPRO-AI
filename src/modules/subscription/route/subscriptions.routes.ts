import { Router } from "express";
import {
  checkoutHandler,
  getCurrentSubscription,
  patchCancelSubscriptionHandler,
  patchUndoCancelSubscriptionHandler
} from "../controllers/subscription.controller.js";
import { changePlanHandler } from "../controllers/plans.controller.js";
import { validateBody } from "../../../validators/validateBody.js";

import { checkoutSchema } from "../../../DTO/checkout.dto.js";
import { changePlanSchema } from "../../../DTO/changePlan.dto.js";

// Import your security middlewares (adjust the path to match your structure)
import {
  authenticateUser,
  requireTenant,
  requirePermission
} from "../../../validators/validateUser.js";

const router = Router();

// 1. Authenticate and attach tenant context to ALL routes in this file
router.use(authenticateUser);
router.use(requireTenant);

router.get("/current", getCurrentSubscription);
router.patch(
  "/current/cancel",
  requirePermission("manage_billing"),
  patchCancelSubscriptionHandler
);

router.patch(
  "/current/cancel/undo",
  requirePermission("manage_billing"),
  patchUndoCancelSubscriptionHandler
);

router.patch(
  "/current/plan",
  requirePermission("manage_billing"),
  validateBody(changePlanSchema),
  changePlanHandler
);

router.post(
  "/checkout",
  requirePermission("manage_billing"),
  validateBody(checkoutSchema),
  checkoutHandler
);
export default router;
