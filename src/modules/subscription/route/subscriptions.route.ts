import { Router } from "express";
import {
  checkoutHandler,
  createSubscriptionRecoveryHandler,
  deleteScheduledPlanChangeHandler,
  getCurrentSubscription,
  patchCancelSubscriptionHandler,
  patchUndoCancelSubscriptionHandler
} from "../controller/subscription.controller.js";
import { changePlanHandler } from "../controller/plans.controller.js";
import { validateBody } from "../../../validators/validateBody.js";

import { checkoutSchema } from "../types/checkout.dto.js";
import { changePlanSchema } from "../types/change-plan.dto.js";

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
router.post(
  "/current/recovery",
  requirePermission("manage_billing"),
  createSubscriptionRecoveryHandler
);
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
router.delete(
  "/current/plan/scheduled",
  requirePermission("manage_billing"),
  deleteScheduledPlanChangeHandler
);
export default router;
