import { Router } from "express";
import { onBoardingHandler } from "./controllers/controller.js";

// Import the modular routers you just created
import plansRoutes from "./route/plans.routes.js";
import promoCodeRoutes from "./route/promo-codes.routes.js";

import subscriptionRoutes from "./route/subscriptions.routes.js";
import invoices from "./route/invoice.routes.js";
const router = Router();

// Existing onboarding route
router.post("/", onBoardingHandler);

// Mount the modular routes to their respective base paths
router.use("/plans", plansRoutes);
router.use("/promo-codes", promoCodeRoutes);
router.use("/", subscriptionRoutes);
router.use("/", invoices);

// Exporting the router directly for consistency with the other routing files
export default router;
