import { Router } from "express";
import { z } from "zod";
import { authenticateUser, requireTenant } from "../../validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../validators/validatePlatformUser.js";
import { validateBody } from "../../validators/validateBody.js";
import { validateParams } from "../../validators/validateParams.js";
import {
  approveCustomPlanQuoteSchema,
  createCustomPlanQuoteSchema,
  customPlanPricingPolicyUpdateSchema,
  customPlanQuoteIdParamsSchema,
  updateCustomPlanQuoteSchema,
  updateVendorRateSchema,
  vendorRateIdParamsSchema,
  vendorRateSchema
} from "../../DTO/customPlan.dto.js";
import { planParamsSchema, planSchema, updatePlanSchema } from "../../DTO/plan.dto.js";
import {
  createPromoCodeSchema,
  promoCodePlanParamsSchema,
  updatePromoCodeSchema
} from "../../DTO/promoCode.dto.js";
import {
  createFeatureSchema,
  featureIdParamSchema,
  updateFeatureSchema
} from "../../DTO/features.dto.js";
import {
  linkFeatureBodySchema,
  planAndFeatureIdParamSchema,
  planIdParamSchema,
  updateFeatureLimitsBodySchema
} from "../../DTO/billing.dto.js";
import {
  patchPlanHandler,
  postPlanHandler
} from "../subscription/controllers/plans.controller.js";
import {
  getPromocodeHandler,
  patchPromocodeHandler,
  postPromocodeHandler
} from "../subscription/controllers/promocode.controller.js";
import { featureController } from "../features/controller/features-managment.controller.js";
import { planFeatureController } from "../features/controller/plan-feature.controller.js";
import {
  approvePlatformQuoteHandler,
  calculatePlatformQuoteHandler,
  createPlatformQuoteHandler,
  createPlatformVendorRateHandler,
  getPlatformPricingPolicyHandler,
  getPlatformQuoteHandler,
  linkPlatformPromoToPlanHandler,
  listPlatformCustomPlansHandler,
  listPlatformPlansHandler,
  listPlatformQuotesHandler,
  listPlatformSubscriptionsHandler,
  listPlatformTenantsHandler,
  listPlatformVendorRatesHandler,
  platformMeHandler,
  rejectPlatformQuoteHandler,
  sendPlatformQuoteHandler,
  setPlatformCustomPlanStatusHandler,
  updatePlatformPricingPolicyHandler,
  updatePlatformQuoteHandler,
  updatePlatformVendorRateHandler
} from "./platform-admin.controller.js";

const router = Router();
router.use(authenticateUser, requireTenant, requirePlatformRole);

router.get("/me", platformMeHandler);

const read = requirePlatformPermission("billing.read");
const manage = requirePlatformPermission("billing.manage");
const pricing = requirePlatformPermission("billing.pricing.manage");

router.get("/billing/tenants", read, listPlatformTenantsHandler);
router.get("/billing/subscriptions", requirePlatformPermission("subscriptions.read"), listPlatformSubscriptionsHandler);

router.get("/billing/plans", read, listPlatformPlansHandler);
router.post("/billing/plans", manage, validateBody(planSchema), postPlanHandler);
router.patch(
  "/billing/plans/:id",
  manage,
  validateParams(planParamsSchema),
  validateBody(updatePlanSchema),
  patchPlanHandler
);

router.get("/billing/custom-plans", read, listPlatformCustomPlansHandler);
router.patch(
  "/billing/custom-plans/:id/status",
  manage,
  validateParams(planParamsSchema),
  validateBody(z.object({ isActive: z.boolean() }).strict()),
  setPlatformCustomPlanStatusHandler
);

const platformQuoteCreateSchema = createCustomPlanQuoteSchema.extend({
  tenantId: z.uuid()
}).strict();

router.get("/billing/custom-quotes", read, listPlatformQuotesHandler);
router.post("/billing/custom-quotes", manage, validateBody(platformQuoteCreateSchema), createPlatformQuoteHandler);
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
router.post("/billing/vendor-rates", pricing, validateBody(vendorRateSchema), createPlatformVendorRateHandler);
router.patch(
  "/billing/vendor-rates/:id",
  pricing,
  validateParams(vendorRateIdParamsSchema),
  validateBody(updateVendorRateSchema),
  updatePlatformVendorRateHandler
);

router.get("/billing/promo-codes", read, getPromocodeHandler);
router.post("/billing/promo-codes", manage, validateBody(createPromoCodeSchema), postPromocodeHandler);
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
router.get("/billing/features/:id", read, validateParams(featureIdParamSchema), featureController.getOne);
router.post("/billing/features", manage, validateBody(createFeatureSchema), featureController.create);
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
router.patch(
  "/billing/plans/:plan_id/features/:feature_id",
  manage,
  validateParams(planAndFeatureIdParamSchema),
  validateBody(updateFeatureLimitsBodySchema),
  planFeatureController.updateLimits
);

export default router;
