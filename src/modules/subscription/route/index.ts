import { Router } from "express";
import {
  authenticateUser,
  requireTenant,
  requirePermission
} from "../../../validators/validateUser.js";
import { onBoardingHandler } from "../controller/onboarding.controller.js";

import plansRoutes from "./plans.route.js";
import promoCodeRoutes from "./promo-codes.route.js";
import subscriptionRoutes from "./subscriptions.route.js";
import invoices from "./invoice.route.js";

const router = Router();

router.post(
  "/",
  authenticateUser,
  requireTenant,
  requirePermission("all"),
  onBoardingHandler
);

router.use("/plans", plansRoutes);
router.use("/promo-codes", promoCodeRoutes);
router.use("/subscriptions", subscriptionRoutes);
router.use("/", invoices);

export default router;
