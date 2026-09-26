import { Router } from "express";
import * as marketIntelligenceController from "../controller/market-int.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";

const router = Router({ mergeParams: true });

// Ensure strict perimeter isolation via middleware
router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/market-intelligence?productId=xyz&periodDays=30
router.get("/", marketIntelligenceController.getMarketOverview);

export default router;
