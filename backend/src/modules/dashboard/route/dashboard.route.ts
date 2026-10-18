import { Router } from "express";
import * as dashboardController from "../controller/dashboard.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { requireFeatureAccess } from "../../../middleware/validators/validateFeatures.js";

// Import your existing auth middlewares here
// import { authenticateUser, requireTenantAccess } from '../../middleware/auth';

// Use mergeParams: true to inherit the :companyId parameter from parent routers
const router = Router({ mergeParams: true });

/**
 * GET /companies/:companyId/dashboard
 * Query Params: ?periodDays=30
 */
router.get(
  "/",
  authenticateUser,
  requireTenant,
  requireFeatureAccess("dashboard_analytics"),
  dashboardController.getAggregate
);

export default router;
