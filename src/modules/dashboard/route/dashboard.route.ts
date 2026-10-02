import { Router } from "express";
import * as dashboardController from "../controller/dashboard.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";

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
  dashboardController.getAggregate
);

export default router;
