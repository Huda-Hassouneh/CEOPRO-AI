import { Router } from "express";
import {
  acceptQuoteHandler,
  approveQuoteHandler,
  calculateQuoteHandler,
  createQuoteHandler,
  createVendorRateHandler,
  getOfferHandler,
  getQuoteHandler,
  listCustomPlansHandler,
  listQuotesHandler,
  listVendorRatesHandler,
  rejectQuoteHandler,
  sendQuoteHandler,
  updateQuoteHandler,
  updateVendorRateHandler,
  getConfiguratorHandler,
  previewCustomPlanHandler,
  requestCustomPlanManualReviewHandler,
  checkoutCustomPlanHandler,
  getPricingPolicyHandler,
  updatePricingPolicyHandler
} from "../controllers/custom-plan.controller.js";
import {
  authenticateUser,
  requirePermission,
  requireTenant
} from "../../../validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../validators/validatePlatformUser.js";
import { validateBody } from "../../../validators/validateBody.js";
import { validateParams } from "../../../validators/validateParams.js";
import {
  approveCustomPlanQuoteSchema,
  createCustomPlanQuoteSchema,
  customPlanQuoteIdParamsSchema,
  updateCustomPlanQuoteSchema,
  updateVendorRateSchema,
  vendorRateIdParamsSchema,
  vendorRateSchema,
  customPlanPreviewSchema,
  customPlanManualReviewSchema,
  customPlanInstantCheckoutSchema,
  customPlanPricingPolicyUpdateSchema
} from "../../../DTO/customPlan.dto.js";

const router = Router();
router.use(authenticateUser, requireTenant);

// Customer self-service custom-plan flow. Pricing is authoritative on the server.
router.get("/configurator", getConfiguratorHandler);
router.post(
  "/preview",
  validateBody(customPlanPreviewSchema),
  previewCustomPlanHandler
);
router.post(
  "/manual-review",
  requirePermission("manage_billing"),
  validateBody(customPlanManualReviewSchema),
  requestCustomPlanManualReviewHandler
);
router.post(
  "/checkout",
  requirePermission("manage_billing"),
  validateBody(customPlanInstantCheckoutSchema),
  checkoutCustomPlanHandler
);

// Internal pricing policy. Keep all cost/margin details out of customer endpoints.
router.get(
  "/pricing-policy",
  requirePlatformRole,
  requirePlatformPermission("billing.read"),
  getPricingPolicyHandler
);
router.patch(
  "/pricing-policy",
  requirePlatformRole,
  requirePlatformPermission("billing.pricing.manage"),
  validateBody(customPlanPricingPolicyUpdateSchema),
  updatePricingPolicyHandler
);

// Tenant-private custom plans and customer-safe offer view.
router.get("/", listCustomPlansHandler);
router.get(
  "/quotes/:id/offer",
  validateParams(customPlanQuoteIdParamsSchema),
  getOfferHandler
);
router.post(
  "/quotes/:id/accept",
  requirePermission("manage_catalog"),
  validateParams(customPlanQuoteIdParamsSchema),
  acceptQuoteHandler
);

// Internal quote management. All pricing values are calculated server-side.
router.get("/quotes", requirePlatformRole, requirePlatformPermission("billing.read"), listQuotesHandler);
router.post(
  "/quotes",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateBody(createCustomPlanQuoteSchema),
  createQuoteHandler
);
router.get(
  "/quotes/:id",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  getQuoteHandler
);
router.patch(
  "/quotes/:id",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  validateBody(updateCustomPlanQuoteSchema),
  updateQuoteHandler
);
router.post(
  "/quotes/:id/calculate",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  calculateQuoteHandler
);
router.post(
  "/quotes/:id/approve",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  validateBody(approveCustomPlanQuoteSchema),
  approveQuoteHandler
);
router.post(
  "/quotes/:id/send",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  sendQuoteHandler
);
router.post(
  "/quotes/:id/reject",
  requirePlatformRole,
  requirePlatformPermission("billing.manage"),
  validateParams(customPlanQuoteIdParamsSchema),
  rejectQuoteHandler
);

// Vendor rates are global internal cost inputs, so only the strongest existing
// tenant permission (all) may mutate/read them.
router.get("/vendor-rates", requirePlatformRole, requirePlatformPermission("billing.read"), listVendorRatesHandler);
router.post(
  "/vendor-rates",
  requirePlatformRole,
  requirePlatformPermission("billing.pricing.manage"),
  validateBody(vendorRateSchema),
  createVendorRateHandler
);
router.patch(
  "/vendor-rates/:id",
  requirePlatformRole,
  requirePlatformPermission("billing.pricing.manage"),
  validateParams(vendorRateIdParamsSchema),
  validateBody(updateVendorRateSchema),
  updateVendorRateHandler
);

export default router;
