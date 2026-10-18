import { Router } from "express";
import {
  requireEntitlement,
  requireFeatureAccess
} from "../../../middleware/validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import {
  analyzePending,
  getSummary
} from "../controller/sentiment.controller.js";
import {
  validateSentimentAnalyzePendingQuery,
  validateSentimentSummaryQuery
} from "../types/sentiment.validation.js";

const router = Router();

router.use(authenticateUser, requireTenant);

router.post(
  "/analyze-pending",
  validateSentimentAnalyzePendingQuery,
  requireEntitlement("sentiment_analysis"),
  analyzePending
);

router.get(
  "/summary",
  validateSentimentSummaryQuery,
  requireFeatureAccess("sentiment_analysis"),
  getSummary
);

export default router;
