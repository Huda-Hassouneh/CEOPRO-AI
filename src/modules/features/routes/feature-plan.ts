import { Router } from "express";
import { planFeatureController } from "../controller/plan-feature.controller.js";
import { usageController } from "../controller/usage.controller.js";

import { validateParams } from "../../../validators/validateParams.js";
import { validateBody } from "../../../validators/validateBody.js";
import {
  linkFeatureBodySchema,
  planAndFeatureIdParamSchema,
  planIdParamSchema,
  updateFeatureLimitsBodySchema
} from "../../../DTO/billing.dto.js";

import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../validators/validatePlatformUser.js";

const router = Router();

// 1. Authenticate and attach tenant context to ALL routes in this file
router.use(authenticateUser);

// GET /plans/:plan_id/features
// Protected endpoint: View all features and limits linked to a specific plan
router.get(
  "/plans/:plan_id/features",
  requirePlatformRole,
  requirePlatformPermission("billing.read"),
  validateParams(planIdParamSchema),
  planFeatureController.getForPlan
);

// POST /plans/:plan_id/features
// Protected endpoint: Link a new feature to a plan
router.post(
  "/plans/:plan_id/features",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(planIdParamSchema),
  validateBody(linkFeatureBodySchema), // Assumes feature_id is inside the body
  planFeatureController.linkFeature
);

// PATCH /plans/:plan_id/features/:feature_id
// Protected endpoint: Update a feature's limits (like changing users_limit from 10 to 50)
router.patch(
  "/plans/:plan_id/features/:feature_id",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(planAndFeatureIdParamSchema),
  validateBody(updateFeatureLimitsBodySchema),
  planFeatureController.updateLimits
);

// GET /subscriptions/current/usage
// Protected endpoint: Tenants can view their own usage dashboard
// (Renamed from /tenant/usage-dashboard to match RESTful namespace)
router.get(
  "/subscriptions/current/usage",
  requireTenant,
  usageController.getDashboard
);

export default router;
