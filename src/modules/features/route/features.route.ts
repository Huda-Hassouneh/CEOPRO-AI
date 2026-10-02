import { Router } from "express";
import multer from "multer";

import {
  requireEntitlement,
  requireFeatureAccess
} from "../../../validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";

// 2. Validators
import {
  ragQuerySchema,
  extractionPendingQuerySchema
} from "../types/features.dto.js";
import { validateQuery } from "../../../validators/validateQuery.js";
import {
  documentController,
  extractionController,
  ragController
} from "../controller/features.controller.js";

const router = Router();

// Configure multer for in-memory file uploads (adjust storage as needed)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: Number(process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024),
    files: 1
  }
});

/**
 * Global Middlewares for this router
 * Every request hitting /api/features must be authenticated and tied to a tenant.
 */
router.use(authenticateUser);
router.use(requireTenant);

// Sentiment routes are owned by src/modules/sentiment and mounted at /features/sentiment.

// MPI routes are owned by src/modules/mpi and mounted at /features/mpi.

// ============================================================================
// 2. RAG Knowledge Assistant [METERED]
router.get(
  "/rag/documents",
  requireEntitlement("document_extraction"),
  documentController.listDocuments
);
// Add this alongside your existing RAG POST route

router.get(
  "/rag/chunks/:chunk_id",
  requireFeatureAccess("rag_assistant"), // Validate subscription access
  ragController.getChunk
);
// ============================================================================
router.post(
  "/rag/query",
  validateQuery(ragQuerySchema),
  requireEntitlement("rag_assistant"),
  ragController.queryAssistant
);

// ============================================================================
// 3. Information Extraction (NER) [METERED]
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
  requireFeatureAccess("document_extraction"),
  extractionController.processPending
);

// Note: Demand Forecasting and Market Scoring are not exposed via direct HTTP
// requests from the frontend in this file, as they rely on Redis streams and
// internal scoring functions respectively.

export default router;
