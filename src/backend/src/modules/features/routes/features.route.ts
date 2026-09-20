import { Router } from "express";
import multer from "multer";

import { requireEntitlement } from "../../../validators/validateFeatures.js";

// 2. Validators
import {
  pricingQuerySchema,
  sentimentBatchQuerySchema,
  subjectSummaryQuerySchema,
  ragQuerySchema,
  extractionPendingQuerySchema
} from "../../../DTO/features.dto.js";
import { validateQuery } from "../../../validators/validateQuery.js";
import {
  extractionController,
  mpiController,
  pricingController,
  ragController,
  sentimentController
} from "../controller/features.controller.js";

const router = Router();

// Configure multer for in-memory file uploads (adjust storage as needed)
const upload = multer({ storage: multer.memoryStorage() });

/**
 * Global Middlewares for this router
 * Every request hitting /api/features must be authenticated and tied to a tenant.
 */
// router.use(authenticateUser);
// router.use(requireTenant);

// ============================================================================
// 1. Pricing Recommendation Engine [METERED]
// ============================================================================
router.post(
  "/pricing/recommend",
  validateQuery(pricingQuerySchema),
  requireEntitlement("ai_pricing"), // Enforces the usage quota
  pricingController.getRecommendation
);

// ============================================================================
// 2. Sentiment Analysis [METERED]
// ============================================================================
router.post(
  "/sentiment/analyze-pending",
  validateQuery(sentimentBatchQuerySchema),
  requireEntitlement("sentiment_analysis"),
  sentimentController.analyzePending
);

router.get(
  "/sentiment/summary",
  validateQuery(subjectSummaryQuerySchema),
  requireEntitlement("sentiment_analysis"),
  sentimentController.getSummary
);

// ============================================================================
// 3. Market Perception Index (MPI) [BOOLEAN - Tier Access]
// ============================================================================
router.get(
  "/mpi/summary",
  validateQuery(subjectSummaryQuerySchema), // Shares the exact same schema as Sentiment summary
  requireEntitlement("market_perception"),
  mpiController.getSummary
);

// ============================================================================
// 4. RAG Knowledge Assistant [METERED]
// ============================================================================
router.post(
  "/rag/query",
  validateQuery(ragQuerySchema),
  requireEntitlement("rag_assistant"),
  ragController.queryAssistant
);

// ============================================================================
// 5. Information Extraction (NER) [METERED]
// ============================================================================
router.post(
  "/extraction/upload",
  requireEntitlement("document_extraction"),
  upload.single("file"), // Middleware to parse multipart/form-data
  extractionController.uploadFile
);

router.post(
  "/extraction/process-pending",
  validateQuery(extractionPendingQuerySchema),
  requireEntitlement("document_extraction"),
  extractionController.processPending
);

// Note: Demand Forecasting and Market Scoring are not exposed via direct HTTP
// requests from the frontend in this file, as they rely on Redis streams and
// internal scoring functions respectively.

export default router;
