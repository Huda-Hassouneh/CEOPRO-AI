import { Router } from "express";
import * as marketIntelligenceController from "../controller/market-int.controller.js";
import { requireEntitlement } from "../../../middleware/validators/validateFeatures.js";
import { validateMarketOverviewQuery } from "../types/market-int.validation.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";

const router = Router({ mergeParams: true });

// Ensure strict perimeter isolation via middleware
router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/market-intelligence?productId=xyz&periodDays=30
router.get("/", requireEntitlement("market_intelligence"), validateMarketOverviewQuery, marketIntelligenceController.getMarketOverview);

export default router;
