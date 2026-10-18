import { Router } from "express";
import { requireFeatureAccess } from "../../../middleware/validators/validateFeatures.js";
import * as forecastingController from "../controller/forecasting.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";

// Ensure mergeParams is true to access :companyId from parent routers
const router = Router({ mergeParams: true });
router.use(
  authenticateUser,
  requireTenant,
  requireFeatureAccess("demand_prediction")
);

// GET /forecasting/demand?periodDays=30&productId=all
router.get("/demand", forecastingController.getOverview);

// GET /forecasting/demand/:productId
router.get("/demand/:productId", forecastingController.getDetail);

// POST /forecasting/demand/:productId/generate { horizon_days?: 1..60 }
router.post(
  "/demand/:productId/generate",
  forecastingController.generateDemand
);

export default router;
