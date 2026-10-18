import { Router } from "express";
import { requireFeatureAccess } from "../../../middleware/validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { recommendPrice, listPricingHistory } from "../controller/pricing.controller.js";
import { validatePricingRecommendationQuery } from "../types/pricing.validation.js";

const router = Router();

router.use(authenticateUser, requireTenant);
router.get('/history',validatePricingRecommendationQuery,requireFeatureAccess('ai_pricing'),listPricingHistory);

router.post(
  "/recommend",
  validatePricingRecommendationQuery,
  // Access is required even for replay. Only NEW work reserves capacity inside
  // the service, so a completed request can be replayed at zero credits.
  requireFeatureAccess("ai_pricing"),
  recommendPrice
);

export default router;
