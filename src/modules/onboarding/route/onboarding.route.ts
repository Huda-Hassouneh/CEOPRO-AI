import { Router } from "express";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { validateBody } from "../../../middleware/validators/validateBody.js";
import {
  completeOnboardingSchema,
  goalsSchema,
  planSchema,
  profileSchema,
  regionalPreferencesSchema
} from "../types/onboarding.dto.js";
import {
  completeHandler,
  getStateHandler,
  saveGoalsHandler,
  savePlanHandler,
  saveProfileHandler,
  saveRegionHandler
} from "../controller/onboarding.controller.js";

const router = Router();

router.use(authenticateUser, requireTenant);

router.get("/state", getStateHandler);
router.patch(
  "/regional-preferences",
  validateBody(regionalPreferencesSchema),
  saveRegionHandler
);
router.patch("/profile", validateBody(profileSchema), saveProfileHandler);
router.patch("/goals", validateBody(goalsSchema), saveGoalsHandler);
router.patch("/plan", validateBody(planSchema), savePlanHandler);
router.post(
  "/complete",
  validateBody(completeOnboardingSchema),
  completeHandler
);

export default router;
