import { Router } from "express";
import { onBoardingHandler } from "../controllers/controller.js";

// Import the modular routers you just created
import plansRoutes from "./plans.routes.js";
import promoCodeRoutes from "./promo-codes.routes.js";
import subscriptionRoutes from "./subscriptions.routes.js";
import invoices from "./invoice.routes.js";

const router = Router();

router.post("/", onBoardingHandler);

router.use("/plans", plansRoutes);
router.use("/promo-codes", promoCodeRoutes);
router.use("/subscriptions", subscriptionRoutes);
router.use("/", invoices);

export default router;
