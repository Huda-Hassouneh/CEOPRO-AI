import { Router } from "express";
import ownerPortalRouter from "../../owner-portal/index.js";
import { z } from "zod";
import platformNotificationRouter from "../../platform-notifications/route/platform-notification.route.js";

import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../middleware/validators/validatePlatformUser.js";
import { validateBody } from "../../../middleware/validators/validateBody.js";
import { validateParams } from "../../../middleware/validators/validateParams.js";
import {
  approveCustomPlanQuoteSchema,
  createCustomPlanQuoteSchema,
  customPlanPricingPolicyUpdateSchema,
  customPlanQuoteIdParamsSchema,
  updateCustomPlanQuoteSchema,
  updateVendorRateSchema,
  infrastructureRateSchema,
  updateInfrastructureRateSchema,
  infrastructureRateIdParamsSchema,
  vendorRateIdParamsSchema,
  vendorRateSchema
} from "../../subscription/types/custom-plan.dto.js";
import {
  planParamsSchema,
  planSchema,
  updatePlanSchema
} from "../../subscription/types/plan.dto.js";
import {
  createPromoCodeSchema,
  promoCodePlanParamsSchema,
  updatePromoCodeSchema
} from "../../subscription/types/promo-code.dto.js";
import {
  createFeatureSchema,
  featureIdParamSchema,
  updateFeatureSchema
} from "../../features/types/features.dto.js";
import {
  linkFeatureBodySchema,
  planAndFeatureIdParamSchema,
  planIdParamSchema,
  updateFeatureLimitsBodySchema
} from "../../features/types/billing.dto.js";
import {
  patchPlanHandler,
  postPlanHandler
} from "../../subscription/controller/plans.controller.js";
import {
  getPromocodeHandler,
  patchPromocodeHandler,
  postPromocodeHandler
} from "../../subscription/controller/promocode.controller.js";
import { featureController } from "../../features/controller/features-management.controller.js";
import { planFeatureController } from "../../features/controller/plan-feature.controller.js";
import {
  approvePlatformQuoteHandler,
  calculatePlatformQuoteHandler,
  createPlatformQuoteHandler,
  createPlatformVendorRateHandler,
  createPlatformInfrastructureRateHandler,
  getPlatformPricingPolicyHandler,
  getPlatformQuoteHandler,
  linkPlatformPromoToPlanHandler,
  listPlatformCustomPlansHandler,
  listPlatformPlansHandler,
  listPlatformQuotesHandler,
  listPlatformSubscriptionsHandler,
  listPlatformTenantsHandler,
  listPlatformVendorRatesHandler,
  listPlatformInfrastructureRatesHandler,
  platformMeHandler,
  rejectPlatformQuoteHandler,
  sendPlatformQuoteHandler,
  setPlatformCustomPlanStatusHandler,
  updatePlatformPricingPolicyHandler,
  updatePlatformQuoteHandler,
  updatePlatformVendorRateHandler,
  updatePlatformInfrastructureRateHandler
} from "../controller/platform-admin.controller.js";

const router = Router();
router.use(authenticateUser, requireTenant, requirePlatformRole);

router.get("/me", platformMeHandler);
router.use(ownerPortalRouter);

const read = requirePlatformPermission("billing.read");
const manage = requirePlatformPermission("billing.manage");
const pricing = requirePlatformPermission("billing.pricing.manage");

router.get("/billing/tenants", read, listPlatformTenantsHandler);
router.get(
  "/billing/subscriptions",
  requirePlatformPermission("subscriptions.read"),
  listPlatformSubscriptionsHandler
);

router.get("/billing/plans", read, listPlatformPlansHandler);
router.post(
  "/billing/plans",
  manage,
  validateBody(planSchema),
  postPlanHandler
);
router.patch(
  "/billing/plans/:id",
  manage,
  validateParams(planParamsSchema),
  validateBody(updatePlanSchema),
  patchPlanHandler
);
router.get(
  "/billing/infrastructure-rates",
  read,
  listPlatformInfrastructureRatesHandler
);
router.post(
  "/billing/infrastructure-rates",
  pricing,
  validateBody(infrastructureRateSchema),
  createPlatformInfrastructureRateHandler
);
router.patch(
  "/billing/infrastructure-rates/:id",
  pricing,
  validateParams(infrastructureRateIdParamsSchema),
  validateBody(updateInfrastructureRateSchema),
  updatePlatformInfrastructureRateHandler
);

router.get("/billing/custom-plans", read, listPlatformCustomPlansHandler);
router.patch(
  "/billing/custom-plans/:id/status",
  manage,
  validateParams(planParamsSchema),
  validateBody(z.object({ isActive: z.boolean() }).strict()),
  setPlatformCustomPlanStatusHandler
);

const platformQuoteCreateSchema = createCustomPlanQuoteSchema
  .extend({
    tenantId: z.uuid()
  })
  .strict();

router.get("/billing/custom-quotes", read, listPlatformQuotesHandler);
router.post(
  "/billing/custom-quotes",
  manage,
  validateBody(platformQuoteCreateSchema),
  createPlatformQuoteHandler
);
router.get(
  "/billing/custom-quotes/:id",
  read,
  validateParams(customPlanQuoteIdParamsSchema),
  getPlatformQuoteHandler
);
router.patch(
  "/billing/custom-quotes/:id",
  manage,
  validateParams(customPlanQuoteIdParamsSchema),
  validateBody(updateCustomPlanQuoteSchema),
  updatePlatformQuoteHandler
);
router.post(
  "/billing/custom-quotes/:id/calculate",
  manage,
  validateParams(customPlanQuoteIdParamsSchema),
  calculatePlatformQuoteHandler
);
router.post(
  "/billing/custom-quotes/:id/approve",
  manage,
  validateParams(customPlanQuoteIdParamsSchema),
  validateBody(approveCustomPlanQuoteSchema),
  approvePlatformQuoteHandler
);
router.post(
  "/billing/custom-quotes/:id/send",
  manage,
  validateParams(customPlanQuoteIdParamsSchema),
  sendPlatformQuoteHandler
);
router.post(
  "/billing/custom-quotes/:id/reject",
  manage,
  validateParams(customPlanQuoteIdParamsSchema),
  rejectPlatformQuoteHandler
);

router.get("/billing/pricing-policy", read, getPlatformPricingPolicyHandler);
router.patch(
  "/billing/pricing-policy",
  pricing,
  validateBody(customPlanPricingPolicyUpdateSchema),
  updatePlatformPricingPolicyHandler
);
router.get("/billing/vendor-rates", read, listPlatformVendorRatesHandler);
router.post(
  "/billing/vendor-rates",
  pricing,
  validateBody(vendorRateSchema),
  createPlatformVendorRateHandler
);
router.patch(
  "/billing/vendor-rates/:id",
  pricing,
  validateParams(vendorRateIdParamsSchema),
  validateBody(updateVendorRateSchema),
  updatePlatformVendorRateHandler
);

router.get("/billing/promo-codes", read, getPromocodeHandler);
router.post(
  "/billing/promo-codes",
  manage,
  validateBody(createPromoCodeSchema),
  postPromocodeHandler
);
router.patch(
  "/billing/promo-codes/:id",
  manage,
  validateParams(planParamsSchema),
  validateBody(updatePromoCodeSchema),
  patchPromocodeHandler
);
router.post(
  "/billing/promo-codes/:promoCodeId/plans/:planId",
  manage,
  validateParams(promoCodePlanParamsSchema),
  linkPlatformPromoToPlanHandler
);

router.get("/billing/features", read, featureController.getAll);
router.get(
  "/billing/features/:id",
  read,
  validateParams(featureIdParamSchema),
  featureController.getOne
);
router.post(
  "/billing/features",
  manage,
  validateBody(createFeatureSchema),
  featureController.create
);
router.delete(
  "/billing/features/:id",
  manage,
  validateParams(featureIdParamSchema),
  featureController.remove
);
router.patch(
  "/billing/features/:id",
  manage,
  validateParams(featureIdParamSchema),
  validateBody(updateFeatureSchema),
  featureController.update
);

router.get(
  "/billing/plans/:plan_id/features",
  read,
  validateParams(planIdParamSchema),
  planFeatureController.getForPlan
);
router.post(
  "/billing/plans/:plan_id/features",
  manage,
  validateParams(planIdParamSchema),
  validateBody(linkFeatureBodySchema),
  planFeatureController.linkFeature
);
router.delete(
  "/billing/plans/:plan_id/features/:feature_id",
  manage,
  validateParams(planAndFeatureIdParamSchema),
  planFeatureController.unlinkFeature
);
router.patch(
  "/billing/plans/:plan_id/features/:feature_id",
  manage,
  validateParams(planAndFeatureIdParamSchema),
  validateBody(updateFeatureLimitsBodySchema),
  planFeatureController.updateLimits
);

router.use(platformNotificationRouter);
export default router;
