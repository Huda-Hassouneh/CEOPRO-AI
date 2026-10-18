import { Router } from "express";

// Import the modular routers you just created
import plansRoutes from "./route/plans.route.js";
import promoCodeRoutes from "./route/promo-codes.route.js";

import subscriptionRoutes from "./route/subscriptions.route.js";
import invoices from "./route/invoice.route.js";
import customPlanRoutes from "./route/custom-plan.route.js";
export { default as stripeWebhookRouter } from "./route/stripe-webhook.route.js";
const router = Router();

// Mount the modular routes to their respective base paths
router.use("/plans", plansRoutes);
router.use("/promo-codes", promoCodeRoutes);
router.use("/custom-plans", customPlanRoutes);
router.use("/", invoices);
router.use("/", subscriptionRoutes);

// Exporting the router directly for consistency with the other routing files
export default router;
