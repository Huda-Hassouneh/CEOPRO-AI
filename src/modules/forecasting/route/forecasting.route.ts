import { Router } from "express";
import * as forecastingController from "../controller/forecasting.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";

// Ensure mergeParams is true to access :companyId from parent routers
const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/forecasting/demand?periodDays=30&productId=all
router.get("/demand", forecastingController.getOverview);

// GET /companies/:companyId/forecasting/demand/:productId
router.get("/demand/:productId", forecastingController.getDetail);

export default router;
