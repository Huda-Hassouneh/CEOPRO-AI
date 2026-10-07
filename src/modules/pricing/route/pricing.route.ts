import { Router } from "express";
import { requireEntitlement } from "../../../middleware/validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { recommendPrice } from "../controller/pricing.controller.js";
import { validatePricingRecommendationQuery } from "../types/pricing.validation.js";

const router = Router();

router.use(authenticateUser, requireTenant);

router.post(
  "/recommend",
  validatePricingRecommendationQuery,
  // requireEntitlement("ai_pricing"),
  recommendPrice
);

export default router;
